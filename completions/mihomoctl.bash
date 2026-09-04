_mihomoctl_complete() {
  local current=${COMP_WORDS[COMP_CWORD]}
  local previous=${COMP_WORDS[COMP_CWORD-1]}
  local commands='start stop restart status ready doctor exec direct diagnose rules logs version update help'
  if (( COMP_CWORD == 1 )); then
    mapfile -t COMPREPLY < <(compgen -W "$commands" -- "$current")
  elif [[ ${COMP_WORDS[1]} == logs ]]; then
    if [[ $previous == --lines ]]; then
      COMPREPLY=()
    else
      mapfile -t COMPREPLY < <(compgen -W '--lines --follow -f' -- "$current")
    fi
  elif [[ ${COMP_WORDS[1]} == update ]]; then
    mapfile -t COMPREPLY < <(compgen -W '--check --version --dry-run --help' -- "$current")
  elif [[ ${COMP_WORDS[1]} == status || ${COMP_WORDS[1]} == ready ]]; then
    mapfile -t COMPREPLY < <(compgen -W '--json' -- "$current")
  elif [[ ${COMP_WORDS[1]} == doctor ]]; then
    mapfile -t COMPREPLY < <(compgen -W '--offline --json' -- "$current")
  elif [[ ${COMP_WORDS[1]} == diagnose ]]; then
    if (( COMP_CWORD == 2 )); then
      mapfile -t COMPREPLY < <(compgen -W 'url process name' -- "$current")
    else
      mapfile -t COMPREPLY < <(compgen -W '--json' -- "$current")
    fi
  elif [[ ${COMP_WORDS[1]} == rules ]]; then
    mapfile -t COMPREPLY < <(compgen -W 'status check --json --home-dir --config' -- "$current")
  else
    COMPREPLY=()
  fi
}
complete -F _mihomoctl_complete mihomoctl
