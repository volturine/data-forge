select_default_playwright_tests() {
    local frontend_root="$1"
    local listed_files
    if ! listed_files="$(cd "$frontend_root" && rg --files tests -g '*.test.ts' | sort)"; then
        echo "Could not discover E2E Playwright tests; ensure ripgrep (rg) is installed." >&2
        return 1
    fi
    if [ -z "$listed_files" ]; then
        echo "No E2E Playwright test files were discovered." >&2
        return 1
    fi

    local normal_files=()
    local test_file
    while IFS= read -r test_file; do
        case "$test_file" in
            tests/runtime-architecture.test.ts|tests/datasource-compute-isolation.test.ts|tests/concurrency.test.ts)
                ;;
            *)
                normal_files+=("$test_file")
                ;;
        esac
    done <<<"$listed_files"

    if [ "${#normal_files[@]}" -eq 0 ]; then
        echo "No ordinary E2E Playwright tests remain after excluding architecture and concurrency tests." >&2
        return 1
    fi
    printf '%s\n' "${normal_files[@]}"
}
