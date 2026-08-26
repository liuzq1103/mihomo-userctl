_mihomoctl_complete() {
  local current=${COMP_WORDS[COMP_CWORD]}
  local previous=${COMP_WORDS[COMP_CWORD-1]}
  local commands='start stop restart status ready doctor logs log version help'
  if (( COMP_CWORD == 1 )); then
    mapfile -t COMPREPLY < <(compgen -W "$commands" -- "$current")
  elif [[ ${COMP_WORDS[1]} == logs || ${COMP_WORDS[1]} == log ]]; then
    if [[ $previous == --lines ]]; then
      COMPREPLY=()
    else
      mapfile -t COMPREPLY < <(compgen -W '--lines --follow -f' -- "$current")
    fi
  else
    COMPREPLY=()
  fi
}
complete -F _mihomoctl_complete mihomoctl
