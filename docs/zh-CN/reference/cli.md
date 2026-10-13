# CLI 命令参考

由实际解析定义生成；初始化前也可使用 `mihomoctl COMMAND --help`。

`mihomoctl [--user|--system] COMMAND [ARGS...] [--json]`

Scope flags precede COMMAND. `exec` and `direct` pass everything after `--` to the child.

Compatibility: `profiles` = `profile list`; `export --binding NAME` = `integration export NAME`; `dashboard` = `ui`; `health` = `health check`. Retired: `codex`, `paseo`, `opencode`, `diagnose`, `ready`.

## init

```text
usage: mihomoctl init [-h] --core CORE [--port PORT] [--config CONFIG]
                      [--allow-non-loopback ALLOW_NON_LOOPBACK] [--json]

options:
  -h, --help            show this help message and exit
  --core CORE
  --port PORT
  --config CONFIG
  --allow-non-loopback ALLOW_NON_LOOPBACK
  --json                emit the mihomoctl/v1 JSON envelope
```

## start

```text
usage: mihomoctl start [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## stop

```text
usage: mihomoctl stop [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## restart

```text
usage: mihomoctl restart [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## status

```text
usage: mihomoctl status [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## logs

```text
usage: mihomoctl logs [-h] [--lines LINES] [--follow] [--json]

options:
  -h, --help     show this help message and exit
  --lines LINES
  --follow
  --json         emit the mihomoctl/v1 JSON envelope
```

## config

```text
usage: mihomoctl config [-h] {validate,check} ...

positional arguments:
  {validate,check}

options:
  -h, --help        show this help message and exit
```

### config validate

```text
usage: mihomoctl config validate [-h] [--file FILE] [--profile PROFILE]
                                 [--json]

options:
  -h, --help         show this help message and exit
  --file FILE
  --profile PROFILE
  --json             emit the mihomoctl/v1 JSON envelope
```

### config check

```text
usage: mihomoctl config check [-h] [--file FILE] [--profile PROFILE] [--json]

options:
  -h, --help         show this help message and exit
  --file FILE
  --profile PROFILE
  --json             emit the mihomoctl/v1 JSON envelope
```

## profile

```text
usage: mihomoctl profile [-h] {list,show,validate,set-default} ...

positional arguments:
  {list,show,validate,set-default}

options:
  -h, --help            show this help message and exit
```

### profile list

```text
usage: mihomoctl profile list [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### profile show

```text
usage: mihomoctl profile show [-h] [--json] name

positional arguments:
  name

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### profile validate

```text
usage: mihomoctl profile validate [-h] [--json] name

positional arguments:
  name

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### profile set-default

```text
usage: mihomoctl profile set-default [-h] [--json] name

positional arguments:
  name

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## env

```text
usage: mihomoctl env [-h] {show,export} ...

positional arguments:
  {show,export}

options:
  -h, --help     show this help message and exit
```

### env show

```text
usage: mihomoctl env show [-h] [--profile PROFILE] [--binding BINDING]
                          [--reveal] [--json]

options:
  -h, --help         show this help message and exit
  --profile PROFILE
  --binding BINDING
  --reveal
  --json             emit the mihomoctl/v1 JSON envelope
```

### env export

```text
usage: mihomoctl env export [-h] [--profile PROFILE] [--binding BINDING]
                            (--output OUTPUT | --reveal) [--json]

options:
  -h, --help         show this help message and exit
  --profile PROFILE
  --binding BINDING
  --output OUTPUT
  --reveal
  --json             emit the mihomoctl/v1 JSON envelope
```

## exec

```text
usage: mihomoctl exec [-h] [--profile PROFILE] [--binding BINDING] [--json]

options:
  -h, --help         show this help message and exit
  --profile PROFILE
  --binding BINDING
  --json             emit the mihomoctl/v1 JSON envelope
```

## direct

```text
usage: mihomoctl direct [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## integration

```text
usage: mihomoctl integration [-h] {list,show,check,export,install,remove} ...

positional arguments:
  {list,show,check,export,install,remove}

options:
  -h, --help            show this help message and exit
```

### integration list

```text
usage: mihomoctl integration list [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### integration show

```text
usage: mihomoctl integration show [-h] [--json] name

positional arguments:
  name

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### integration check

```text
usage: mihomoctl integration check [-h] [--json] name

positional arguments:
  name

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### integration export

```text
usage: mihomoctl integration export [-h] [--output-dir OUTPUT_DIR] [--reveal]
                                    [--json]
                                    name

positional arguments:
  name

options:
  -h, --help            show this help message and exit
  --output-dir OUTPUT_DIR
  --reveal
  --json                emit the mihomoctl/v1 JSON envelope
```

### integration install

```text
usage: mihomoctl integration install [-h] [--json] name

positional arguments:
  name

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### integration remove

```text
usage: mihomoctl integration remove [-h] [--json] name

positional arguments:
  name

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## service

```text
usage: mihomoctl service [-h]
                         {install,start,stop,restart,status,uninstall} ...

positional arguments:
  {install,start,stop,restart,status,uninstall}

options:
  -h, --help            show this help message and exit
```

### service install

```text
usage: mihomoctl service install [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### service start

```text
usage: mihomoctl service start [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### service stop

```text
usage: mihomoctl service stop [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### service restart

```text
usage: mihomoctl service restart [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### service status

```text
usage: mihomoctl service status [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### service uninstall

```text
usage: mihomoctl service uninstall [-h] [--dry-run] [--json]

options:
  -h, --help  show this help message and exit
  --dry-run
  --json      emit the mihomoctl/v1 JSON envelope
```

## tun

```text
usage: mihomoctl tun [-h] {status,enable,disable} ...

positional arguments:
  {status,enable,disable}

options:
  -h, --help            show this help message and exit
```

### tun status

```text
usage: mihomoctl tun status [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### tun enable

```text
usage: mihomoctl tun enable [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### tun disable

```text
usage: mihomoctl tun disable [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## core

```text
usage: mihomoctl core [-h] {install,update,adopt,list} ...

positional arguments:
  {install,update,adopt,list}

options:
  -h, --help            show this help message and exit
```

### core install

```text
usage: mihomoctl core install [-h] --version VERSION [--sha256 SHA256]
                              [--dry-run] [--json]

options:
  -h, --help         show this help message and exit
  --version VERSION
  --sha256 SHA256
  --dry-run
  --json             emit the mihomoctl/v1 JSON envelope
```

### core update

```text
usage: mihomoctl core update [-h] --version VERSION [--sha256 SHA256]
                             [--dry-run] [--json]

options:
  -h, --help         show this help message and exit
  --version VERSION
  --sha256 SHA256
  --dry-run
  --json             emit the mihomoctl/v1 JSON envelope
```

### core adopt

```text
usage: mihomoctl core adopt [-h] --path PATH [--json]

options:
  -h, --help   show this help message and exit
  --path PATH
  --json       emit the mihomoctl/v1 JSON envelope
```

### core list

```text
usage: mihomoctl core list [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## health

```text
usage: mihomoctl health [-h] [--profile PROFILE] [--binding BINDING]
                        [--egress-url EGRESS_URL] [--json]

options:
  -h, --help            show this help message and exit
  --profile PROFILE
  --binding BINDING
  --egress-url EGRESS_URL
  --json                emit the mihomoctl/v1 JSON envelope
```

## doctor

```text
usage: mihomoctl doctor [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## migrate

```text
usage: mihomoctl migrate [-h] (--dry-run | --apply) [--remove-loader]
                         [--no-import] [--core CORE] [--json]

options:
  -h, --help       show this help message and exit
  --dry-run
  --apply
  --remove-loader
  --no-import
  --core CORE
  --json           emit the mihomoctl/v1 JSON envelope
```

## rollback

```text
usage: mihomoctl rollback [-h] [--json] backup

positional arguments:
  backup

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## update

```text
usage: mihomoctl update [-h] [--dry-run] [--allow-same-version]
                        [--allow-downgrade] [--wheelhouse WHEELHOUSE]
                        [--python PYTHON] [--json]
                        [source]

positional arguments:
  source

options:
  -h, --help            show this help message and exit
  --dry-run
  --allow-same-version
  --allow-downgrade
  --wheelhouse WHEELHOUSE
  --python PYTHON
  --json                emit the mihomoctl/v1 JSON envelope
```

## rules

```text
usage: mihomoctl rules [-h] {status,check} ...

positional arguments:
  {status,check}

options:
  -h, --help      show this help message and exit
```

### rules status

```text
usage: mihomoctl rules status [-h] [--home-dir HOME_DIR] [--config CONFIG]
                              [--json]

options:
  -h, --help           show this help message and exit
  --home-dir HOME_DIR
  --config CONFIG
  --json               emit the mihomoctl/v1 JSON envelope
```

### rules check

```text
usage: mihomoctl rules check [-h] [--home-dir HOME_DIR] [--config CONFIG]
                             [--json]

options:
  -h, --help           show this help message and exit
  --home-dir HOME_DIR
  --config CONFIG
  --json               emit the mihomoctl/v1 JSON envelope
```

## version

```text
usage: mihomoctl version [-h] [--json]

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## controller

```text
usage: mihomoctl controller [-h] {status,initialize,setup,token} ...

positional arguments:
  {status,initialize,setup,token}

options:
  -h, --help            show this help message and exit
```

### controller status

```text
usage: mihomoctl controller status [-h] [--config CONFIG] [--json]

options:
  -h, --help       show this help message and exit
  --config CONFIG
  --json           emit the mihomoctl/v1 JSON envelope
```

### controller initialize

```text
usage: mihomoctl controller initialize [-h] [--port PORT]
                                       [--home-dir HOME_DIR] [--config CONFIG]
                                       [--json]

options:
  -h, --help           show this help message and exit
  --port PORT
  --home-dir HOME_DIR
  --config CONFIG
  --json               emit the mihomoctl/v1 JSON envelope
```

### controller setup

```text
usage: mihomoctl controller setup [-h] [--port PORT] [--home-dir HOME_DIR]
                                  [--archive ARCHIVE] [--sha256 SHA256]
                                  [--config CONFIG] [--json]

options:
  -h, --help           show this help message and exit
  --port PORT
  --home-dir HOME_DIR
  --archive ARCHIVE
  --sha256 SHA256
  --config CONFIG
  --json               emit the mihomoctl/v1 JSON envelope
```

### controller token

```text
usage: mihomoctl controller token [-h] [--config CONFIG] [--json]

options:
  -h, --help       show this help message and exit
  --config CONFIG
  --json           emit the mihomoctl/v1 JSON envelope
```

## nodes

```text
usage: mihomoctl nodes [-h] [--config CONFIG] [--json]

options:
  -h, --help       show this help message and exit
  --config CONFIG
  --json           emit the mihomoctl/v1 JSON envelope
```

## groups

```text
usage: mihomoctl groups [-h] [--config CONFIG] [--json]

options:
  -h, --help       show this help message and exit
  --config CONFIG
  --json           emit the mihomoctl/v1 JSON envelope
```

## select

```text
usage: mihomoctl select [-h] [--config CONFIG] [--json] group node

positional arguments:
  group
  node

options:
  -h, --help       show this help message and exit
  --config CONFIG
  --json           emit the mihomoctl/v1 JSON envelope
```

## latency

```text
usage: mihomoctl latency [-h] [--config CONFIG] [--json] node

positional arguments:
  node

options:
  -h, --help       show this help message and exit
  --config CONFIG
  --json           emit the mihomoctl/v1 JSON envelope
```

## connections

```text
usage: mihomoctl connections [-h] [--details] [--config CONFIG] [--json]

options:
  -h, --help       show this help message and exit
  --details
  --config CONFIG
  --json           emit the mihomoctl/v1 JSON envelope
```

## traffic

```text
usage: mihomoctl traffic [-h] [--config CONFIG] [--json]

options:
  -h, --help       show this help message and exit
  --config CONFIG
  --json           emit the mihomoctl/v1 JSON envelope
```

## subscription

```text
usage: mihomoctl subscription [-h] {preview,apply} ...

positional arguments:
  {preview,apply}

options:
  -h, --help       show this help message and exit
```

### subscription preview

```text
usage: mihomoctl subscription preview [-h] [--source-file SOURCE_FILE]
                                      [--url-file URL_FILE] [--stdin]
                                      [--policy {auto,nodes,provider}]
                                      [--home-dir HOME_DIR] [--config CONFIG]
                                      [--json]

options:
  -h, --help            show this help message and exit
  --source-file SOURCE_FILE
  --url-file URL_FILE
  --stdin
  --policy {auto,nodes,provider}
  --home-dir HOME_DIR
  --config CONFIG
  --json                emit the mihomoctl/v1 JSON envelope
```

### subscription apply

```text
usage: mihomoctl subscription apply [-h] --sha256 SHA256 [--home-dir HOME_DIR]
                                    [--config CONFIG] [--json]
                                    id

positional arguments:
  id

options:
  -h, --help           show this help message and exit
  --sha256 SHA256
  --home-dir HOME_DIR
  --config CONFIG
  --json               emit the mihomoctl/v1 JSON envelope
```

## tui

```text
usage: mihomoctl tui [-h] [--home-dir HOME_DIR] [--plain]
                     [--engine {curses,textual,plain}] [--theme {dark,light}]
                     [--ascii] [--stdin] [--policy {auto,nodes,provider}]
                     [--script SCRIPT] [--details] [--flclash-compat]
                     [--config CONFIG] [--json]

options:
  -h, --help            show this help message and exit
  --home-dir HOME_DIR
  --plain
  --engine {curses,textual,plain}
  --theme {dark,light}
  --ascii
  --stdin
  --policy {auto,nodes,provider}
  --script SCRIPT
  --details
  --flclash-compat
  --config CONFIG
  --json                emit the mihomoctl/v1 JSON envelope
```

## providers

```text
usage: mihomoctl providers [-h] [--config CONFIG] [--json]

options:
  -h, --help       show this help message and exit
  --config CONFIG
  --json           emit the mihomoctl/v1 JSON envelope
```

## provider

```text
usage: mihomoctl provider [-h] {refresh} ...

positional arguments:
  {refresh}

options:
  -h, --help  show this help message and exit
```

### provider refresh

```text
usage: mihomoctl provider refresh [-h] [--config CONFIG] [--json] name

positional arguments:
  name

options:
  -h, --help       show this help message and exit
  --config CONFIG
  --json           emit the mihomoctl/v1 JSON envelope
```

## dns

```text
usage: mihomoctl dns [-h] [--config CONFIG] [--json] name [record]

positional arguments:
  name
  record

options:
  -h, --help       show this help message and exit
  --config CONFIG
  --json           emit the mihomoctl/v1 JSON envelope
```

## mode

```text
usage: mihomoctl mode [-h] [--config CONFIG] [--json] {rule,global,direct}

positional arguments:
  {rule,global,direct}

options:
  -h, --help            show this help message and exit
  --config CONFIG
  --json                emit the mihomoctl/v1 JSON envelope
```

## health-check

```text
usage: mihomoctl health-check [-h] [--apply] [--home-dir HOME_DIR]
                              [--config CONFIG] [--url URL]
                              [--expected-status EXPECTED_STATUS]
                              [--interval INTERVAL] [--timeout TIMEOUT]
                              [--lazy {true,false}] [--tolerance TOLERANCE]
                              [--preset {resilient}] [--json]
                              {group,provider} name

positional arguments:
  {group,provider}
  name

options:
  -h, --help            show this help message and exit
  --apply
  --home-dir HOME_DIR
  --config CONFIG
  --url URL
  --expected-status EXPECTED_STATUS
  --interval INTERVAL
  --timeout TIMEOUT
  --lazy {true,false}
  --tolerance TOLERANCE
  --preset {resilient}
  --json                emit the mihomoctl/v1 JSON envelope
```

## manual

```text
usage: mihomoctl manual [-h] [--apply] [--home-dir HOME_DIR] [--config CONFIG]
                        [--json]
                        group

positional arguments:
  group

options:
  -h, --help           show this help message and exit
  --apply
  --home-dir HOME_DIR
  --config CONFIG
  --json               emit the mihomoctl/v1 JSON envelope
```

## override

```text
usage: mihomoctl override [-h] --script SCRIPT [--apply] [--flclash-compat]
                          [--home-dir HOME_DIR] [--config CONFIG] [--json]

options:
  -h, --help           show this help message and exit
  --script SCRIPT
  --apply
  --flclash-compat
  --home-dir HOME_DIR
  --config CONFIG
  --json               emit the mihomoctl/v1 JSON envelope
```

## ui

```text
usage: mihomoctl ui [-h] [--config CONFIG] [--json]

options:
  -h, --help       show this help message and exit
  --config CONFIG
  --json           emit the mihomoctl/v1 JSON envelope
```
