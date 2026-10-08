#!/usr/bin/env bash
set -uo pipefail

mode="${1:-}"
if [[ "$mode" != pre && "$mode" != post ]]; then
	echo "usage: $0 pre|post" >&2
	exit 2
fi

warn() {
	echo "::warning::$*" >&2
}

is_e2e_project() {
	[[ "$1" == dataforge-test-* || "$1" == dataforge-e2e-ci-* ]]
}

list_projects() {
	local output project volume network
	local -a projects=()

	if output="$(docker ps -a --filter label=com.docker.compose.project --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null)"; then
		while IFS= read -r project; do
			if is_e2e_project "$project"; then projects+=("$project"); fi
		done <<<"$output"
	else
		warn 'Could not list Compose containers while cleaning stale E2E resources.'
	fi

	if output="$(docker volume ls -q --filter label=com.docker.compose.project 2>/dev/null)"; then
		while IFS= read -r volume; do
			[[ -n "$volume" ]] || continue
			project="$(docker volume inspect --format '{{index .Labels "com.docker.compose.project"}}' "$volume" 2>/dev/null)" || {
				warn "Could not inspect Compose volume ${volume}."
				continue
			}
			if is_e2e_project "$project"; then projects+=("$project"); fi
		done <<<"$output"
	else
		warn 'Could not list Compose volumes while cleaning stale E2E resources.'
	fi

	if output="$(docker network ls -q --filter label=com.docker.compose.project 2>/dev/null)"; then
		while IFS= read -r network; do
			[[ -n "$network" ]] || continue
			project="$(docker network inspect --format '{{index .Labels "com.docker.compose.project"}}' "$network" 2>/dev/null)" || {
				warn "Could not inspect Compose network ${network}."
				continue
			}
			if is_e2e_project "$project"; then projects+=("$project"); fi
		done <<<"$output"
	else
		warn 'Could not list Compose networks while cleaning stale E2E resources.'
	fi

	if ((${#projects[@]})); then
		printf '%s\n' "${projects[@]}" | sort -u
	fi
}

wait_for_teardown() {
	local deadline=$((SECONDS + 60)) previous='' current='' have_previous=0
	while ((SECONDS < deadline)); do
		if ! current="$(docker ps -a --filter label=com.docker.compose.project --format '{{.Label "com.docker.compose.project"}} {{.State}}' 2>/dev/null | awk '$1 ~ /^dataforge-(test|e2e-ci)-/ { print }')"; then
			warn 'Could not inspect E2E container teardown state; proceeding with cleanup retries.'
			return
		fi
		if grep -Eq ' (created|restarting|removing)$' <<<"$current"; then
			have_previous=0
			sleep 2
			continue
		fi
		if ((have_previous)) && [[ "$current" == "$previous" ]]; then return; fi
		previous="$current"
		have_previous=1
		sleep 2
	done
	warn 'E2E container teardown was still changing after 60 seconds; proceeding with cleanup retries.'
}

remove_containers() {
	local project="$1" output id
	local -a ids=()
	if ! output="$(docker ps -aq --filter "label=com.docker.compose.project=${project}" 2>/dev/null)"; then
		warn "Could not list containers for Compose project ${project}."
		return
	fi
	[[ -n "$output" ]] || return
	while IFS= read -r id; do
		[[ -n "$id" ]] && ids+=("$id")
	done <<<"$output"
	if ! docker rm -f "${ids[@]}" >/dev/null 2>&1; then
		warn "Could not remove all containers for Compose project ${project}."
	fi
}

remove_project_volumes() {
	local project="$1" output volume holders holder_id
	local -a volumes=() holder_ids=()
	if ! output="$(docker volume ls -q --filter "label=com.docker.compose.project=${project}" 2>/dev/null)"; then
		warn "Could not list volumes for Compose project ${project}."
		return
	fi
	[[ -n "$output" ]] || return
	while IFS= read -r volume; do
		[[ -n "$volume" ]] && volumes+=("$volume")
	done <<<"$output"
	for volume in "${volumes[@]}"; do
		holder_ids=()
		if ! holders="$(docker ps -aq --filter "volume=${volume}" 2>/dev/null)"; then
			warn "Could not list containers holding volume ${volume}."
		else
			if [[ -n "$holders" ]]; then
				while IFS= read -r holder_id; do
					[[ -n "$holder_id" ]] && holder_ids+=("$holder_id")
				 done <<<"$holders"
				if ! docker rm -f "${holder_ids[@]}" >/dev/null 2>&1; then
					warn "Could not remove every container holding volume ${volume}."
				fi
			fi
		fi
		if ! docker volume rm "$volume" >/dev/null 2>&1; then
			warn "Could not remove E2E volume ${volume}; it may still be in use."
		fi
	done
}

remove_project_networks() {
	local project="$1" output network
	local -a networks=()
	if ! output="$(docker network ls -q --filter "label=com.docker.compose.project=${project}" 2>/dev/null)"; then
		warn "Could not list networks for Compose project ${project}."
		return
	fi
	[[ -n "$output" ]] || return
	while IFS= read -r network; do
		[[ -n "$network" ]] && networks+=("$network")
	done <<<"$output"
	if ! docker network rm "${networks[@]}" >/dev/null 2>&1; then
		warn "Could not remove all networks for Compose project ${project}."
	fi
}

clean_compose_projects() {
	local attempt empty_passes=0 project
	local -a projects=()
	wait_for_teardown
	for attempt in {1..20}; do
		projects=()
		while IFS= read -r project; do
			[[ -n "$project" ]] && projects+=("$project")
		done < <(list_projects)
		if ((${#projects[@]} == 0)); then
			empty_passes=$((empty_passes + 1))
			if ((empty_passes == 2)); then return; fi
		else
			empty_passes=0
			for project in "${projects[@]}"; do
				remove_containers "$project"
				remove_project_volumes "$project"
				remove_project_networks "$project"
			done
		fi
		if ((attempt < 20)); then sleep 3; fi
	done
	projects=()
	while IFS= read -r project; do
		[[ -n "$project" ]] && projects+=("$project")
	done < <(list_projects)
	if ((${#projects[@]})); then
		warn "E2E Docker resources remain after cleanup retries: ${projects[*]}"
	fi
}

clean_workspace_artifacts() {
	local workspace="${GITHUB_WORKSPACE:-}"
	if [[ -z "$workspace" ]]; then
		warn 'GITHUB_WORKSPACE is unavailable; could not remove stale E2E artifacts.'
		return
	fi
	if ! docker run --rm --user 0:0 --entrypoint sh \
		--volume "${workspace}:/workspace" \
		docker:29.7.2-dind \
		-c 'rm -rf /workspace/.e2e-artifacts /workspace/.test-artifacts' >/dev/null 2>&1; then
		warn 'Could not remove stale E2E artifact directories.'
	fi
}

clean_runner_images() {
	local output image
	if ! output="$(docker image ls --filter 'reference=dataforge-test-runner:*' --format '{{.Repository}}:{{.Tag}}' 2>/dev/null)"; then
		warn 'Could not list stale E2E runner images.'
	else
		while IFS= read -r image; do
			[[ -n "$image" ]] || continue
			if ! docker image rm "$image" >/dev/null 2>&1; then
				warn "Could not remove E2E runner image ${image}."
			fi
		done <<<"$output"
	fi
	if ! docker builder prune --force --filter until=72h >/dev/null 2>&1; then
		warn 'Could not prune stale Docker build cache.'
	fi
}

clean_compose_projects
clean_runner_images
clean_workspace_artifacts
