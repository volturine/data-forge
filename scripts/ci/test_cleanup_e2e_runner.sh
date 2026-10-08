#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
temp_dir="$(mktemp -d)"
trap 'rm -rf "$temp_dir"' EXIT
mkdir -p "$temp_dir/bin" "$temp_dir/state"
export E2E_DOCKER_FAKE_STATE="$temp_dir/state"
export GITHUB_WORKSPACE="$temp_dir/workspace"

cat >"$temp_dir/bin/docker" <<'DOCKER'
#!/usr/bin/env bash
set -euo pipefail

state_dir="$E2E_DOCKER_FAKE_STATE"
get_state() {
	if [[ -f "$state_dir/$1" ]]; then cat "$state_dir/$1"; else echo 0; fi
}
set_state() {
	echo "$2" >"$state_dir/$1"
}

case "$1" in
	ps)
		format=''
		volume_filter=''
		project_filter=''
		for arg in "$@"; do
			if [[ "$arg" == *'{{.State}}'* ]]; then format='state'; fi
			if [[ "$arg" == *'{{.Label "com.docker.compose.project"}}'* ]]; then format="${format:-project}"; fi
			if [[ "$arg" == volume=* ]]; then volume_filter="${arg#volume=}"; fi
			if [[ "$arg" == label=com.docker.compose.project=* ]]; then
				project_filter="${arg#label=com.docker.compose.project=}"
			fi
		done
		if [[ "$format" == state ]]; then
			if [[ "$(get_state late_created)" == 1 && "$(get_state late_removed)" == 0 ]]; then
				polls="$(get_state late_state_polls)"
				polls=$((polls + 1))
				set_state late_state_polls "$polls"
				if ((polls < 3)); then
					echo 'dataforge-test-race created'
				else
					echo 'dataforge-test-race running'
				fi
			elif [[ "$(get_state initial_removed)" == 0 ]]; then
				echo 'dataforge-test-race running'
			fi
		elif [[ -n "$volume_filter" ]]; then
			if [[ "$volume_filter" == dataforge-test-race_workspace && "$(get_state late_created)" == 1 && "$(get_state late_removed)" == 0 ]]; then
				echo id-late
			fi
		elif [[ -n "$project_filter" ]]; then
			if [[ "$project_filter" == dataforge-test-race ]]; then
				if [[ "$(get_state initial_removed)" == 0 ]]; then echo id-initial; fi
				if [[ "$(get_state late_created)" == 1 && "$(get_state late_removed)" == 0 ]]; then echo id-late; fi
			fi
		elif [[ "$format" == project ]]; then
			if [[ "$(get_state initial_removed)" == 0 || "$(get_state late_created)" == 1 ]]; then
				echo dataforge-test-race
			fi
		fi
		;;
	rm)
		for id in "${@:3}"; do
			case "$id" in
				id-initial) set_state initial_removed 1 ;;
				id-late) set_state late_removed 1 ;;
			esac
			echo "$id" >>"$state_dir/removed-containers"
		done
		;;
	volume)
		case "$2" in
			ls)
				if [[ "$(get_state volume_removed)" == 0 ]]; then echo dataforge-test-race_workspace; fi
				;;
			inspect)
				echo dataforge-test-race
				;;
			rm)
				attempts="$(get_state volume-rm-attempts)"
				attempts=$((attempts + 1))
				set_state volume-rm-attempts "$attempts"
				if ((attempts == 1)); then
					set_state late_created 1
					echo 'volume is in use' >&2
					exit 1
				fi
				set_state volume_removed 1
				;;
			*) exit 2 ;;
		esac
		;;
	network)
		case "$2" in
			ls)
				if [[ "$(get_state network_removed)" == 0 ]]; then echo dataforge-test-race_default; fi
				;;
			inspect)
				echo dataforge-test-race
				;;
			rm) set_state network_removed 1 ;;
			*) exit 2 ;;
		esac
		;;
	image)
		case "$2" in
			ls) ;;
			rm) ;;
			*) exit 2 ;;
		esac
		;;
	builder)
		;;
	run)
		;;
	*)
		echo "Unexpected docker command: $*" >&2
		exit 2
		;;
esac
DOCKER

cat >"$temp_dir/bin/sleep" <<'SLEEP'
#!/usr/bin/env bash
exit 0
SLEEP

chmod +x "$temp_dir/bin/docker" "$temp_dir/bin/sleep"
set +e
output="$(PATH="$temp_dir/bin:$PATH" bash "$repo_root/scripts/ci/cleanup_e2e_runner.sh" post 2>&1)"
status=$?
set -e
if ((status != 0)); then
	echo "Cleanup helper exited with status ${status}. Output:" >&2
	echo "$output" >&2
	exit "$status"
fi

if [[ "$(cat "$temp_dir/state/volume-rm-attempts")" != 2 ]]; then
	echo "Expected cleanup to retry the volume-in-use race. Output:" >&2
	echo "$output" >&2
	exit 1
fi
if ! grep -q 'id-late' "$temp_dir/state/removed-containers"; then
	echo "Expected cleanup to remove the late-created container. Output:" >&2
	echo "$output" >&2
	exit 1
fi
if [[ "$(cat "$temp_dir/state/volume_removed")" != 1 ]]; then
	echo "Expected cleanup to remove the volume after retry. Output:" >&2
	echo "$output" >&2
	exit 1
fi

echo 'E2E cleanup retries a late-created container holding a Compose volume.'
