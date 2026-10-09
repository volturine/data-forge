#!/usr/bin/env bash
# Exercises the Compose teardown policy of scripts/test_container.sh without
# Docker: the STRICT_TEST_TEARDOWN derivation, and compose_down's handling of a
# failed/timed-out `down` in strict and non-strict mode. The function and the
# case block are extracted from the real script so the test tracks its code.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
script="$repo_root/scripts/test_container.sh"
temp_dir="$(mktemp -d)"
trap 'rm -rf "$temp_dir"' EXIT
mkdir -p "$temp_dir/bin"

sed -n '/^case "\${STRICT_TEST_TEARDOWN:-}" in/,/^esac/p' "$script" > "$temp_dir/strict_case.sh"
sed -n '/^compose_down() {/,/^}/p' "$script" > "$temp_dir/compose_down.sh"
[[ -s "$temp_dir/strict_case.sh" && -s "$temp_dir/compose_down.sh" ]] \
    || { echo 'Could not extract the teardown code from test_container.sh.' >&2; exit 1; }

# A `timeout` that behaves like coreutils timeout hitting its bound; it echoes
# its arguments so the log captures the bound and the `down` invocation.
cat > "$temp_dir/bin/timeout" <<'FAKE'
#!/usr/bin/env bash
echo "timeout $*"
exit 124
FAKE
cat > "$temp_dir/bin/compose" <<'FAKE'
#!/usr/bin/env bash
echo "compose $*"
exit 0
FAKE
chmod +x "$temp_dir/bin/timeout" "$temp_dir/bin/compose"

failures=0
fail() {
    echo "FAIL: $*" >&2
    failures=$((failures + 1))
}

expect_strict() {
    local ci="$1" override="$2" expected="$3" actual
    actual="$(CI="$ci" STRICT_TEST_TEARDOWN="$override" bash -c \
        "set -euo pipefail; source '$temp_dir/strict_case.sh'; echo \"\$strict_teardown\"")"
    [[ "$actual" == "$expected" ]] \
        || fail "CI='$ci' STRICT_TEST_TEARDOWN='$override': expected strict_teardown=$expected, got $actual"
}
expect_strict '' '' 1
expect_strict true '' 0
expect_strict true 1 1
expect_strict '' 0 0

invalid_output="$(STRICT_TEST_TEARDOWN=yes TEST_TARGET=test-frontend "$script" 2>&1)" && invalid_status=0 || invalid_status=$?
[[ "$invalid_status" -eq 2 && "$invalid_output" == *"STRICT_TEST_TEARDOWN must be 0 or 1"* ]] \
    || fail "invalid STRICT_TEST_TEARDOWN: expected exit 2 with usage message, got exit $invalid_status: $invalid_output"

# Runs compose_down once with the given strictness and initial status; prints
# "<status after>|<stdout>|<stderr>" for assertions.
run_compose_down() {
    local strict="$1" initial_status="$2" github_actions="$3"
    PATH="$temp_dir/bin:$PATH" GITHUB_ACTIONS="$github_actions" bash -c "
        set -euo pipefail
        strict_teardown=$strict
        status=$initial_status
        compose_down_attempted=0
        artifacts_dir='$temp_dir'
        compose=('$temp_dir/bin/compose')
        source '$temp_dir/compose_down.sh'
        compose_down > '$temp_dir/stdout' 2> '$temp_dir/stderr'
        printf '%s|%s|%s' \"\$status\" \"\$(cat '$temp_dir/stdout')\" \"\$(cat '$temp_dir/stderr')\"
    "
}

result="$(run_compose_down 1 0 '')"
[[ "$result" == "124|"*"Test Compose cleanup failed (exit 124)"* ]] \
    || fail "strict teardown failure should set status 124 and report it; got: $result"
[[ "$result" != *"::warning"* ]] || fail "strict mode should not emit a GitHub Actions warning; got: $result"

result="$(run_compose_down 1 7 '')"
[[ "$result" == "7|"* ]] || fail "strict teardown failure must not mask an earlier failure status 7; got: $result"

result="$(run_compose_down 0 0 true)"
[[ "$result" == "0|::warning title=Test Compose cleanup failed::"*"|Warning: Test Compose cleanup failed (exit 124)"*"The test result is unaffected." ]] \
    || fail "non-strict teardown failure in GitHub Actions should keep status 0 and warn; got: $result"

result="$(run_compose_down 0 0 '')"
[[ "$result" == "0||Warning: Test Compose cleanup failed (exit 124)"* ]] \
    || fail "non-strict teardown failure outside GitHub Actions should keep status 0 with a plain warning; got: $result"

result="$(run_compose_down 0 7 true)"
[[ "$result" == "7|"* ]] || fail "non-strict teardown failure must keep an earlier failure status 7; got: $result"

grep -q -- '--kill-after=5s 90s .*compose down --timeout 10 --volumes --remove-orphans' "$temp_dir/compose-down.log" \
    || fail "compose-down.log should capture a 90s-bounded down with --timeout 10; got: $(cat "$temp_dir/compose-down.log")"

if [[ "$failures" -ne 0 ]]; then
    echo "${failures} teardown policy check(s) failed." >&2
    exit 1
fi
echo 'test_container.sh teardown policy checks passed.'
