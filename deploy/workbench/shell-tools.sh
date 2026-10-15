# Bash 登录终端和 Jupyter 交互终端共用；不在非交互任务中输出文本。
if [ -n "${BASH_VERSION:-}" ]; then
    case "$-" in
        *i*)
            if [ -r /usr/share/bash-completion/bash_completion ] && [ -z "${BASH_COMPLETION_VERSINFO:-}" ]; then
                . /usr/share/bash-completion/bash_completion
            fi
            alias ll='ls -alF'
            alias la='ls -A'
            ;;
    esac
fi
