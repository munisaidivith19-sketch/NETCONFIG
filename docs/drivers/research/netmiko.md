# Netmiko 4.x behaviour for arista_eos, juniper_junos, aruba_aoscx (push engine with custom config-mode entry and safe-rollback commits)

Method note: the source was read directly from **netmiko 4.8.0**. That version is pinned in `backend/requirements.txt` and installed in `backend/.venv/Lib/site-packages/netmiko/`. PyPI lists 4.8.0 as the latest release (21 Sep 2026; 4.7.0 came out 12 May 2026) — [PyPI netmiko](https://pypi.org/project/netmiko/). All line numbers below refer to the 4.8.0 wheel. The upstream paths are `https://github.com/ktbyers/netmiko/blob/develop/netmiko/<path>`. The `develop` copy of `aruba/aruba_aoscx.py` was fetched and matches 4.8.0 — [GitHub develop aruba_aoscx.py](https://raw.githubusercontent.com/ktbyers/netmiko/develop/netmiko/aruba/aruba_aoscx.py). Line numbers on `develop` may differ slightly from 4.8.0.

Source URLs used below:
- [arista.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/arista/arista.py)
- [juniper.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/juniper/juniper.py)
- [aruba_aoscx.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/aruba/aruba_aoscx.py)
- [base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/base_connection.py)
- [cisco_base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/cisco_base_connection.py)
- [ssh_dispatcher.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/ssh_dispatcher.py)
- [no_enable.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/no_enable.py)

## Q1. Which device_type strings exist (SSH / telnet / serial)?

### Takeaway
SSH strings: `arista_eos`, `juniper_junos` (plus the alias `juniper`) and `aruba_aoscx`. Each also accepts an `_ssh` suffix. Telnet exists only for `arista_eos_telnet` and `juniper_junos_telnet`. **There is no `aruba_aoscx_telnet`, and none of the three has a `_serial` variant.** The only serial strings registered are `cisco_ios_serial` and `furukawa_fitelnet_serial`.

### Cited Findings
- `CLASS_MAPPER_BASE` maps `"arista_eos": AristaSSH` (ssh_dispatcher.py L213), `"aruba_aoscx": ArubaCxSSH` (L216), `"juniper": JuniperSSH` (L320) and `"juniper_junos": JuniperSSH` (L321) — [ssh_dispatcher.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/ssh_dispatcher.py)
- A loop at about L400–406 adds an alias `k + "_ssh"` for every base key, so `arista_eos_ssh`, `juniper_junos_ssh` and `aruba_aoscx_ssh` are also valid — [ssh_dispatcher.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/ssh_dispatcher.py)
- Telnet entries: `CLASS_MAPPER["arista_eos_telnet"] = AristaTelnet` (L418) and `CLASS_MAPPER["juniper_junos_telnet"] = JuniperTelnet` (L457). No `aruba_aoscx_telnet` appears in the telnet list. The only Aruba/HP telnet entries are `aruba_procurve_telnet` and `hp_procurve_telnet`, which map to HPProcurveTelnet, a different OS — [ssh_dispatcher.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/ssh_dispatcher.py)
- Serial entries: only `CLASS_MAPPER["cisco_ios_serial"]` and `CLASS_MAPPER["furukawa_fitelnet_serial"]` (L479–481) — [ssh_dispatcher.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/ssh_dispatcher.py)
- BaseConnection picks the transport from the string: `"_telnet" in device_type` gives telnet, `"_serial" in device_type` gives serial, anything else gives ssh (base_connection.py L448–455) — [base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/base_connection.py)
- `ConnectHandler` raises `ValueError("Unsupported 'device_type' ...")` for any string not in `platforms` (L504–516) — [ssh_dispatcher.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/ssh_dispatcher.py)
- File-transfer (SCP) classes exist for `arista_eos` (AristaFileTransfer) and `juniper_junos` (JuniperFileTransfer), but not for aruba_aoscx (L380–392) — [ssh_dispatcher.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/ssh_dispatcher.py)
- AristaTelnet and JuniperTelnet differ from their SSH classes only in setting `default_enter="\r\n"` (arista.py L113–117, juniper.py L263–267) — [arista.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/arista/arista.py), [juniper.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/juniper/juniper.py)

### Inferences
- For a serial console on EOS, Junos or AOS-CX, Netmiko has no ready-made driver. Two options follow from the code: subclass the vendor class and pass a `_serial` device_type yourself (BaseConnection selects serial from the substring, but `ConnectHandler` will reject an unregistered string, so you would instantiate the class directly), or use `generic` / `terminal_server` and drive the session manually. Either way, prove it in the lab before relying on it.
- For a lab console reached over telnet on AOS-CX, the same problem applies: `aruba_aoscx_telnet` does not exist.

### Gaps
- I did not check whether a later commit on `develop` (after 4.8.0) adds `aruba_aoscx_telnet` or serial variants. Only `aruba_aoscx.py` itself was compared.

## Q2. Per-class session_preparation, config-mode methods and prompt patterns

### Takeaway
- **Arista** subclasses CiscoSSHConnection. It sends `terminal width 511` and `terminal length 0` (the length command is the inherited default; Netmiko waits for "Pagination disabled"). Config mode is entered with `configure terminal` and detected by `)#`. It exits with `end`.
- **Junos** uses NoEnable plus BaseConnection. It sends `set cli screen-width 511`, `set cli complete-on-space off` and `set cli screen-length 0`. Config mode is entered with `configure` and detected by `]` (from `[edit]`). It exits with `exit configuration-mode`.
- **AOS-CX** subclasses CiscoSSHConnection. It sends `no page`. Config mode is entered with `configure term` and detected by the literal string `(config)#`. It exits with `end` (inherited).

### Cited Findings
**Arista (`AristaBase(CiscoSSHConnection)`)**
- `prompt_pattern = r"[$>#]"` (L13).
- `session_preparation` (L15–26) does the following in order:
  - sets `ansi_escape_codes=True`;
  - calls `_test_channel_read`;
  - calls `set_terminal_width(command="terminal width 511", pattern=r"Width set to")` inside a try that ignores a timeout;
  - calls `disable_paging(cmd_verify=False, pattern=r"Pagination disabled")`, which uses the inherited default command;
  - calls `set_base_prompt()`.
  - Source: [arista.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/arista/arista.py)
- `check_config_mode(check_string=")#", pattern=r"[>\#]", force_regex=False)` (L59–77) sends RETURN, reads until `[>#]`, removes `"(s1)"` and `"(s2)"` (supervisor markers), and then returns `")#" in output` — [arista.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/arista/arista.py)
- `config_mode(config_command="configure terminal", pattern="", re_flags=0)` (L79–96): when no pattern is given, it builds `re.escape(base_prompt[:16]) + ".*" + re.escape(")#")` with `re.DOTALL` and calls the parent — [arista.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/arista/arista.py)
- `exit_config_mode` is not overridden, so it inherits `CiscoBaseConnection.exit_config_mode(exit_config="end", pattern=r"#.*")` (cisco_base_connection.py L57–59) — [cisco_base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/cisco_base_connection.py)
- `enable()` is overridden with `enable_pattern=r"\#"` (L43–57) — [arista.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/arista/arista.py)

**Juniper (`JuniperBase(NoEnable, BaseConnection)`)**
- `session_preparation` (L17–31) does the following:
  - calls `_test_channel_read(pattern=r"[%>$#]")`;
  - calls `enter_cli_mode()`, which detects a root shell (`root@`, `%`, `$`) and sends `cli`;
  - sends `set cli screen-width 511`;
  - sends `set cli complete-on-space off`;
  - sends `set cli screen-length 0`;
  - calls `set_base_prompt()`.
  - Source: [juniper.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/juniper/juniper.py)
- `check_config_mode(check_string="]", pattern=r"(?m:[>#] $)", force_regex=False)` (L69–84). Its docstring explains why it does not use `#`: "Juniper unfortunately will use # as a message indicator when not in config mode. For example, with commit confirmed." — [juniper.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/juniper/juniper.py)
- `config_mode(config_command="configure", pattern=r"(?s:Entering configuration mode.*\].*#)", re_flags=0)` (L86–99) — [juniper.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/juniper/juniper.py)
- `exit_config_mode(exit_config="exit configuration-mode", pattern="")` (L101–121). Details are under Q4.
- NoEnable makes `check_enable_mode()` return True and makes `enable()` / `exit_enable_mode()` return `""` — [no_enable.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/no_enable.py)
- `cleanup()` (L240–256) calls `exit_config_mode()` if the session is in config mode, swallows any exception, and then sends `exit`. This means a disconnect while in config mode answers "yes" to the uncommitted-changes prompt (see Q4) — [juniper.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/juniper/juniper.py)

**Aruba AOS-CX (`ArubaCxSSH(CiscoSSHConnection)`)**
- `__init__` sets `default_enter="\r"` unless one is given (L15–18) — [aruba_aoscx.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/aruba/aruba_aoscx.py)
- `session_preparation` (L20–24): sets `ansi_escape_codes=True`, calls `_test_channel_read(pattern=r"[>#]")`, calls `set_base_prompt()`, then calls `disable_paging(command="no page")`. It does not set a terminal width — [aruba_aoscx.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/aruba/aruba_aoscx.py)
- `check_config_mode(check_string="(config)#", pattern=r"[>#]")` (L26–32) — [aruba_aoscx.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/aruba/aruba_aoscx.py)
- `config_mode(config_command="configure term", ...)` (L34–43), with the docstring "Aruba auto completes on space so 'configure' needs fully spelled-out." — [aruba_aoscx.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/aruba/aruba_aoscx.py)
- `exit_config_mode` is inherited from Cisco (`end`, `#.*`) — [cisco_base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/cisco_base_connection.py)

**Generic base (applies to all three)**
- `BaseConnection.config_mode` (L2144–2168) works as follows:
  - if `check_config_mode()` is False, it writes `config_command`;
  - if `global_cmd_verify is not False`, it reads until the escaped command echo;
  - it then reads until `pattern` (or until the prompt);
  - it calls `check_config_mode()` again and raises `ValueError("Failed to enter configuration mode.")` if that is still False;
  - if already in config mode, it sends nothing.
  - Source: [base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/base_connection.py)
- `BaseConnection.exit_config_mode` (L2170–2192) runs only `if self.check_config_mode()`. It writes the exit command, reads the echo and the pattern, and raises `ValueError("Failed to exit configuration mode")` if still in config mode — [base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/base_connection.py)

### Inferences
- **AOS-CX pitfall (important):** `check_config_mode` checks for the literal string `(config)#`. In an AOS-CX sub-context the prompt looks like `switch(config-if)#` or `switch(config-vlan-10)#`, which does not contain `(config)#`. So while in a sub-context, Netmiko believes it is not in config mode. Two consequences follow:
  - `exit_config_mode()` silently does nothing, because its guard returns False. A `send_config_set(...)` with the default `exit_config_mode=True` that ends inside an interface context will leave the session in that context and will not raise an error.
  - `config_mode()` called from a sub-context will send `configure term` again.
  - The push engine should either end every AOS-CX command block with `exit`/`end` itself, or pass `check_string=")#"` (or subclass the driver). Verify on the AOS-CX Simulator.
- The Arista and Cisco check (`")#"`) cannot tell `(config)#` apart from `(config-s-NAME)#`. If the engine needs to know it is inside a session, it must search the prompt for `config-s-` itself.

### Gaps
- I did not verify the exact AOS-CX sub-context prompt strings against HPE documentation. `(config-if)#` and `(config-vlan-N)#` come from general knowledge and should be confirmed in the simulator.

## Q3. Do custom entry commands work: `configure session NAME` on Arista and `configure private` on Junos?

### Takeaway
**Arista:** yes, as far as the code shows. The session prompt contains `)#` and starts with the base prompt, so both `check_config_mode` and the default `config_mode` pattern match it. **Junos:** yes on success. `configure private` prints "Entering configuration mode" and `[edit]`, which the default pattern expects. If the device rejects the private session, though, that pattern never matches, and you get a ReadTimeout rather than a clean error.

### Cited Findings
- Arista's session prompt example is `switch(config-s-sess-1)#`, and `commit timer` is shown as `switch(config-s-MySession)# commit timer 01:00:00` — [Arista Session Management Commands](https://www.arista.com/en/um-eos/eos-session-management-commands)
- Arista: "the prompt changes to show the first six characters of the session name" — [Arista Configuration Sessions Overview](https://www.arista.com/en/um-eos/eos-configuration-sessions-overview)
- Arista `config_mode` waits for `base_prompt[:16] + ".*" + ")#"` (DOTALL), and `check_config_mode` returns `")#" in output` — [arista.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/arista/arista.py)
- `BaseConnection.config_mode` sends the command only if `check_config_mode()` is False. If the session is already in `(config)#`, `config_mode("configure session X")` therefore sends **nothing**. You must start from exec mode (`#`) — [base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/base_connection.py)
- Junos `config_mode` uses `pattern=r"(?s:Entering configuration mode.*\].*#)"` and `check_config_mode` looks for `]` — [juniper.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/juniper/juniper.py)
- Junos private mode gives each user a separate private candidate. On conflicts, "the first commit operation takes precedence." When committing, Junos checks that no other user has modified the running configuration. "Merge conflicts can occur when you issue the update command." — [Junos configure command (HPE Networking docs)](https://networkingdocs.hpe.com/documentation/us/en/software/junos/cli/topics/topic-map/configure-command.html)
- A community wiki shows the private-mode start warning "warning: uncommitted changes will be discarded on exit". I found no Juniper page quoting it — [thefreetelecomuni wiki (via search)](https://thefreetelecomuni.atlassian.net/wiki/x/JAAtPw)
- On chassis clusters, plain `configure` puts the user in private mode — [Juniper search result summary: configure command](https://www.juniper.net/documentation/us/en/software/junos/cli/topics/topic-map/configure-command.html)

### Inferences
- Recommended Arista pattern:
  1. `conn.config_mode(config_command="configure session nc_<jobid>")` from exec mode. Netmiko's built-in check confirms only `)#`.
  2. Read `find_prompt()` and assert it contains `config-s-`.
  3. Send the commands with `send_config_set(cmds, enter_config_mode=False, exit_config_mode=False, error_pattern=...)`.
  4. Commit or abort explicitly (see Q5).
  - Keep the session name short and unique. The prompt shows only the first 6 characters, but Netmiko matches only `base_prompt[:16].*)#`, so truncation does not break matching.
- Recommended Junos pattern: `conn.config_mode(config_command="configure private")`. If another user holds `configure exclusive`, or the shared candidate has uncommitted changes, Junos is expected to print an error instead of "Entering configuration mode". Netmiko will then raise `ReadTimeout` (netmiko/exceptions.py) after `read_timeout`, not a descriptive error. Wrap the call and capture the channel output for the job record.

### Gaps
- I could not find the exact Junos error text printed when `configure private` is refused (for example, because the shared database was modified by others). Capture it in the vJunos lab.
- I found no source on whether `configure private` behaves differently on vJunos-switch versus vJunos-router.

## Q4. Junos commit() and exit_config_mode() details, and {master:0} handling

### Takeaway
`commit(confirm=False, confirm_delay=None, check=False, comment="", and_quit=False, read_timeout=120.0, delay_factor=None)` builds one of `commit`, `commit check` or `commit confirmed [N]`, optionally adding ` comment "…"` and ` and-quit`. It enters config mode if needed (plain `configure`). It detects failure **only** by the absence of a success marker string, and then raises `ValueError` with the full output. `exit_config_mode` answers **"yes"** to "Exit with uncommitted changes", which in private or exclusive mode discards the changes. It does **not** handle a differently worded prompt such as "Discard uncommitted changes?". Context lines like `{master:0}` and `[edit]` are stripped from the last line of output.

### Cited Findings
- Signature and validation (juniper.py L123–163):
  - `check` together with `confirm`, `confirm_delay` or `comment` raises `ValueError("Invalid arguments supplied with commit check")`;
  - `confirm_delay` without `confirm` raises `ValueError`;
  - `delay_factor` is deprecated.
  - Source: [juniper.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/juniper/juniper.py)
- Commands and success markers (L166–186):
  - default: `"commit"`, marker `"commit complete"`;
  - check: `"commit check"`, marker `"configuration check succeeds"`;
  - confirm: `"commit confirmed"` or `"commit confirmed " + str(confirm_delay)`, marker `"commit confirmed will be automatically rolled back in"`;
  - comment: appends ` comment "<comment>"` and raises `ValueError` if the comment contains `"`;
  - and_quit: appends `" and-quit"`.
  - Source: [juniper.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/juniper/juniper.py)
- Execution (L188–206): calls `self.config_mode()` with the default `configure`, which is a no-op if already in config mode, including private mode. It then calls `_send_command_str(command_string, expect_string=rf"(?:{re.escape(base_prompt)}|[>#]\s*$)", strip_prompt=False, strip_command=False, read_timeout=read_timeout)`. If the marker is missing, it raises `ValueError(f"Commit failed with the following errors:\n\n{output}")` — [juniper.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/juniper/juniper.py)
- There is no dedicated method to confirm a pending `commit confirmed`. Confirmation is done by calling `commit()` again (a plain `commit`, or `commit check`, which Junos also accepts as confirmation). That is how Junos works; Netmiko just sends the string — [juniper.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/juniper/juniper.py)
- `exit_config_mode` (L101–121):
  1. If in config mode, sends `exit configuration-mode` and waits for `(?:>|Exit with uncommitted changes)`.
  2. If "Exit with uncommitted changes" appears, sends `yes` and waits for `>`.
  3. Raises `ValueError("Failed to exit configuration mode")` if still in config mode.
  - Source: [juniper.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/juniper/juniper.py)
- Juniper's own docs (older 13.1 page, as summarised by search): exiting with uncommitted changes shows "Exit with uncommitted changes? [yes,no] (yes)". Also, "the exit configuration-mode command exits with uncommitted changes without having to respond to a prompt … useful when you are using scripts" — [Juniper 13.1: entering/exiting configuration mode](https://juniper.net/documentation/en_US/junos13.1/topics/task/configuration/junos-cli-configuration-mode-entering-exiting.html). These two statements conflict: Netmiko's code still handles the prompt as a precaution.
- Exclusive mode: "When you use the yes option to exit configure exclusive mode, Junos OS discards any uncommitted changes" — [Junos configure command](https://networkingdocs.hpe.com/documentation/us/en/software/junos/cli/topics/topic-map/configure-command.html)
- `strip_prompt` is overridden to call `strip_context_items`, which removes the **last line** if it matches `\[edit.*\]`, `\{master:?.*\}`, `\{backup:?.*\}`, `\{line.*\}`, `\{primary.*\}` or `\{secondary.*\}` (L208–238). Only the last line is checked, so a `{master:0}` banner in the middle of the output is kept — [juniper.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/juniper/juniper.py)
- `check_config_mode` deliberately keys on `]` rather than `#`, because Junos prints `#` as a message indicator after `commit confirmed` (docstring L75–83) — [juniper.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/juniper/juniper.py)
- Junos has no `save_config` override. It inherits `BaseConnection.save_config`, which raises `NotImplementedError` (base_connection.py L2549–2551), because commit is the save on Junos — [base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/base_connection.py)

### Inferences
- Recommended safe Junos flow with Netmiko:
  1. Enter with `config_mode("configure private")`.
  2. Send the commands with `send_config_set(cmds, enter_config_mode=False, exit_config_mode=False, error_pattern=r"error:|syntax error|unknown command")`.
  3. Run `commit(check=True)`.
  4. Run `commit(confirm=True, confirm_delay=N, comment="netconfig job …")`.
  5. Verify with `show` commands. In config mode, prefix them with `run`, or exit first and re-enter.
  6. Run `commit()` (optionally `and_quit=True`) to confirm.
  7. On failure, run `rollback 0` and then `exit_config_mode()`, or simply let the confirm timer expire.
- Danger: `send_config_set` defaults to `exit_config_mode=True`, and Junos `exit_config_mode` answers "yes". In private mode, an accidental early exit throws away the candidate without any error. Always pass `exit_config_mode=False` until the commit has been made.
- Danger: `commit()` uses the default `read_timeout=120`. A slow vJunos commit could exceed this. Pass a larger `read_timeout`.
- `commit confirmed` output followed by `#` lines is why Juniper's `check_config_mode` does not trust `#`. The push engine's own mode detection should follow the same rule.

### Gaps
- I found no official current Juniper page giving the exact exit-prompt wording for **private** mode (for example, whether it says "Discard uncommitted changes?"). If the wording differs from "Exit with uncommitted changes", Netmiko's `exit_config_mode` would wait for `>` and time out. Test on vJunos.
- I found no Juniper page stating whether `commit confirmed` is allowed in `configure private` mode. It is widely used, but it should be verified in the lab.

## Q5. Arista: commit/session helpers, and what `end`/`exit` do inside a configure session

### Takeaway
Netmiko has **no** Arista commit, session or abort helper. `AristaBase` does not override `commit()`, so it inherits `BaseConnection.commit()`, which raises `AttributeError("Network device does not support 'commit()' method")`. Netmiko's `exit_config_mode` for Arista sends `end`. Arista's docs say you can exit a session and later return to it with `configure session NAME`, which implies that leaving does **not** commit. I found **no** official statement on whether `end` commits a session. Treat this as unverified, and always send `commit`, `commit timer …` or `abort` explicitly.

### Cited Findings
- `BaseConnection.commit()` raises `AttributeError("Network device does not support 'commit()' method")` (base_connection.py L2545–2547), and arista.py defines no `commit` — [base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/base_connection.py), [arista.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/arista/arista.py)
- Arista: you can "exit from the session and return to the same session by running the configure session again." `commit` "commit[s] the changes and replace[s] the current running-config". `abort` will "Abort the session and discard all changes." `service configuration session max pending number` "Sets a limit on the maximum number of uncommitted sessions that can be outstanding." — [Arista Configuration Sessions Overview](https://www.arista.com/en/um-eos/eos-configuration-sessions-overview)
- Arista command syntax: `configure session [session_name] [abort | commit | [description description]]`. `abort` "Ends the configuration sessions and deletes it". `commit` "Commits the changes executed during the session". A commit "replaces running-config with the session configuration", which overwrites running-config changes made after the session started — [Arista Session Management Commands](https://www.arista.com/en/um-eos/eos-session-management-commands)
- `commit timer hh:mm:ss` "can automatically roll back changes performed during a configuration session if you haven't confirmed them within a preset time interval". The example is `switch(config-s-MySession)# commit timer 01:00:00`, followed by a `switch#` prompt. `no commit timer` deletes the session — [Arista Session Management Commands](https://www.arista.com/en/um-eos/eos-session-management-commands)
- The Arista page's examples are inconsistent: after a plain `commit`, the prompt stays at `(config-s-sess-1)#`, but after `commit timer` it returns to `switch#` — [Arista Session Management Commands](https://www.arista.com/en/um-eos/eos-session-management-commands)
- Netmiko Arista `exit_config_mode` sends `end` (inherited Cisco default) — [cisco_base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/cisco_base_connection.py)

### Inferences
- Likely confirm step after `commit timer`: `configure session <NAME> commit` from exec mode, based on the documented syntax `configure session [name] [commit]`. Arista's page does not explicitly spell out the confirm step, so verify on cEOS.
- Recommended Arista flow:
  1. `config_mode("configure session nc_<id>")`.
  2. `send_config_set(..., enter_config_mode=False, exit_config_mode=False, error_pattern=r"% ?(Invalid|Incomplete|Ambiguous)")`.
  3. Optionally `send_command("show session-config diffs", expect_string=r"\)#")` for preview.
  4. `send_command("commit timer 00:05:00", expect_string=r"#")`.
  5. Verify.
  6. `send_command("configure session nc_<id> commit")`.
  7. On failure: `configure session nc_<id> abort`, or let the timer expire.
  - Never rely on Netmiko's `exit_config_mode()` / `end` to commit or to discard.
- Because `send_config_set` defaults to `exit_config_mode=True` (sending `end`), a session could be left pending. Pending sessions count toward the max-pending limit, so the engine should always `abort` on any failure path. The `show session-config diffs` command name is from general knowledge, not from the fetched pages; verify it.

### Gaps
- **Not resolved:** whether `end` inside `configure session` commits, leaves the session pending, or prompts. No Arista page I could read (one page returned HTTP 403) states this explicitly. Test on cEOS-lab before relying on either behaviour.
- The exact way to confirm a `commit timer` (`configure session NAME commit` versus `commit` again inside the session) is unconfirmed.
- The EOS version that introduced `commit timer` was not found.

## Q6. Aruba AOS-CX: class, paging, config mode, save, checkpoint helper

### Takeaway
The class is `ArubaCxSSH(CiscoSSHConnection)`. Session setup sends `no page`, config mode is entered with `configure term` and detected by `(config)#`, and the session exits with `end`. `save_config()` is inherited from CiscoBaseConnection and sends **`copy running-config startup-config`**, not `write memory`. Netmiko has **no checkpoint helper** for AOS-CX. Its rollback feature, `checkpoint auto <minutes>` with a confirm step, must be driven manually, and the exact confirm syntax is disputed between sources.

### Cited Findings
- Class definition, `default_enter="\r"`, `no page`, `(config)#` and `configure term` are covered under Q2 — [aruba_aoscx.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/aruba/aruba_aoscx.py)
- `CiscoBaseConnection.save_config(cmd="copy running-config startup-config", confirm=False, confirm_response="")` (cisco_base_connection.py L230–259):
  - calls `self.enable()` first;
  - if `confirm=False`, uses `_send_command_str(cmd, strip_prompt=False, strip_command=False, read_timeout=100.0)`;
  - if `confirm=True`, uses timing-based sends plus `confirm_response` (or RETURN).
  - Arista and ArubaCx both inherit this unchanged.
  - Source: [cisco_base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/cisco_base_connection.py)
- AOS-CX `checkpoint auto <minutes>` starts a rollback timer, and `checkpoint confirm` "applies the configuration changes permanently, cancelling the automatic rollback" (third-party blog) — [Sikich: Aruba CX checkpoint auto](https://www.sikich.com/insight/how-to-use-aruba-cx-checkpoint-auto-commands/)
- A community post gives the confirm form as `checkpoint auto confirm`, with auto-checkpoints named `AUTO<YYYYMMDDHHMMSS>`. The two sources conflict on the confirm syntax — [HPE Airheads: AOS-CX checkpoints and auto-rollback](https://airheads.hpe.com/discussion/arubaos-cx-configuration-checkpoints-and-auto-rollback)
- On 8320 / 10.04, rollback reportedly did not fire when the SSH session dropped. This was acknowledged as a bug and reported fixed around 10.06.0010 — [Aruba community: checkpoint auto failure after admin disconnect](https://community.arubanetworks.com/discussion/aos-cx-8320-checkpoint-auto-minutes-failure-after-admin-disconnect)
- From late 10.12, auto checkpoints reportedly go into a separate "auto-confirm-backup" category (forum report) — [HPE Airheads search result](https://airheads.hpe.com/discussion/arubaos-cx-configuration-checkpoints-and-auto-rollback)

### Inferences
- Because `checkpoint auto` behaviour depends on the AOS-CX version and the sources disagree, the project's plan of "backup_restore" rollback for AOS-CX is the safer default. `checkpoint auto` could be added later as an experimental option after simulator testing.
- `default_enter="\r"` matters if the push engine writes raw strings with `write_channel`. Use `conn.RETURN` / `normalize_cmd` rather than hard-coding `\n`.

### Gaps
- I did not obtain the official HPE AOS-CX command reference for `checkpoint auto` (mode, exact confirm keyword, prompts). Sources are community and third-party only.
- I did not verify from HPE docs that AOS-CX accepts `copy running-config startup-config`. It is widely used, but the Netmiko default should be confirmed in the simulator. `write memory` is the commonly cited alternative.

## Q7. send_config_set with enter_config_mode=False / exit_config_mode=False / cmd_verify=True, platform overrides

### Takeaway
None of the three classes overrides `send_config_set`, so all use `BaseConnection.send_config_set`. With `cmd_verify=True`, each command is written, the echo is awaited (`re.escape(cmd.strip())`), and then Netmiko reads until `base_prompt.*$` or `terminator.*$` (default `#`). That works for EOS, Junos and AOS-CX config prompts, which all end in `#`. The main risks are interactive prompts that never return `#`, banners (cmd_verify is turned off automatically), and the defaults `exit_config_mode=True` and `read_timeout=15`.

### Cited Findings
- Signature (base_connection.py L2213–2229): `send_config_set(config_commands=None, *, exit_config_mode=True, read_timeout=None, delay_factor=None, max_loops=None, strip_prompt=False, strip_command=False, config_mode_command=None, cmd_verify=True, enter_config_mode=True, error_pattern="", terminator=r"#", bypass_commands=None)` — [base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/base_connection.py)
- `global_cmd_verify`, if set on the connection, overrides `cmd_verify` (L2269–2270). `read_timeout` defaults to 15 s (L2293–2294) — [base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/base_connection.py)
- `bypass_commands` defaults to `r"^banner .*$"`. If **any** command matches, cmd_verify is disabled for the **whole** set (L2306–2319) — [base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/base_connection.py)
- When `enter_config_mode=True`, it calls `config_mode(config_mode_command)` if one was given, otherwise `config_mode()` (L2323–2327) — [base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/base_connection.py)
- The cmd_verify loop (L2356–2378) works per command:
  - write the command;
  - `read_until_pattern(re.escape(cmd.strip()))`;
  - `read_until_pattern(f"(?:{re.escape(self.base_prompt)}.*$|{terminator}.*$)", re_flags=re.M)`;
  - then check `error_pattern` against the **accumulated** output and raise `ConfigInvalidException("Invalid input detected at command: {cmd}, matched error: …")` on the first match.
  - Source: [base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/base_connection.py)
- With `cmd_verify=False` and an `error_pattern`, it uses `read_channel_timing` after each command and checks errors incrementally (L2336–2354) — [base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/base_connection.py)
- When `exit_config_mode=True`, it calls the platform `exit_config_mode()`: `end` on Arista and AOS-CX, `exit configuration-mode` plus an auto-"yes" on Junos (L2380–2381) — [base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/base_connection.py)

### Inferences
- **Sending commands one by one** (one `send_config_set([cmd], enter_config_mode=False, exit_config_mode=False, error_pattern=…)` per command) works on all three platforms and gives exact "stopped at command X" reporting. Because the error check runs on accumulated output, per-call batches of one keep errors attributed to the right command.
- The echo wait uses the exact command text. If a device rewrites or wraps the echo (long lines, or AOS-CX auto-completing on space), the read can time out. Junos and Arista set a width of 511; AOS-CX sets no width. Keep AOS-CX commands short and fully spelled out, or set `cmd_verify=False` for AOS-CX with an `error_pattern`.
- `terminator="#"` means any `#` in output (for example, a Junos message after `commit confirmed`) can end the read early. Use `send_command` with an explicit `expect_string` for commit commands, as `JuniperBase.commit()` does.
- The cmd_verify path wraps each read in `read_until_pattern`, which raises `ReadTimeout` on a hang. A command that triggers a `[yes,no]` / `[y/n]` prompt will raise `ReadTimeout` after 15 s rather than an error. Route such commands through `send_command(..., expect_string=…)` instead.

### Gaps
- I did not check whether `_sanitize_output` or `strip_ansi_escape_codes` alters AOS-CX echoes enough to break `cmd_verify`. Lab testing is needed.

## Q8. send_command with expect_string for interactive prompts

### Takeaway
`send_command(command_string, expect_string=None, read_timeout=10.0, …, cmd_verify=True)` reads until the `expect_string` regex if given, otherwise until the prompt it detects automatically. It is the right tool for commit, confirm and abort steps and for `[yes,no]` prompts, since none of the three platforms overrides it. The internal helper `_send_command_str` (used by `commit()` and `save_config()`) is the same thing, typed to return `str`.

### Cited Findings
- Signature (base_connection.py L1671–1690): `send_command(self, command_string, expect_string=None, read_timeout=10.0, delay_factor=None, max_loops=None, auto_find_prompt=True, strip_prompt=True, strip_command=True, normalize=True, use_textfsm=False, …, cmd_verify=True, raise_parsing_error=False)` — [base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/base_connection.py)
- If `expect_string is not None`, `search_pattern = expect_string`; otherwise `search_pattern = self._prompt_handler(auto_find_prompt)` (about L1783–1786) — [base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/base_connection.py)
- Netmiko itself uses this pattern on these platforms:
  - Junos exit: `expect_string=r"(?:>|Exit with uncommitted changes)"`, then `"yes"` with `expect_string=r">"` (juniper.py L108–118);
  - Junos commit: `expect_string=rf"(?:{re_prompt}|[>#]\s*$)"` (L193–201);
  - Arista bash: `expect_string=r"[\$#]"` (arista.py L100).
  - Sources: [juniper.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/juniper/juniper.py), [arista.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/arista/arista.py)
- `ConfigInvalidException` and `ReadTimeout` are defined in netmiko/exceptions.py (L35, L53) — [exceptions.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/exceptions.py)

### Inferences
- For every interactive step, pass an `expect_string` that matches **both** the prompt question and the normal prompt, for example `r"(\[yes,no\]|\[y/n\]|#\s*$|>\s*$)"`. Then branch on the output, as Netmiko's own Junos `exit_config_mode` does.
- In config mode, `send_command` with `auto_find_prompt=True` calls `find_prompt`. On Junos this works (the base prompt is `user@host`). On Arista and AOS-CX the config prompt differs from the exec prompt, so prefer an explicit `expect_string=r"#\s*$"` for commands sent in config mode.

### Gaps
- None beyond the vendor prompt texts noted in Q3–Q6.

## Q9. save_config() implementations

### Takeaway
Arista and AOS-CX both inherit `CiscoBaseConnection.save_config` (`copy running-config startup-config`, `read_timeout=100`, calls `enable()` first). Junos has none: it inherits `BaseConnection.save_config`, which raises `NotImplementedError`, and you use `commit()` instead.

### Cited Findings
- `CiscoBaseConnection.save_config(cmd="copy running-config startup-config", confirm=False, confirm_response="")` (cisco_base_connection.py L230–259) — [cisco_base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/cisco_base_connection.py)
- `BaseConnection.save_config` raises `NotImplementedError` (base_connection.py L2549–2551). juniper.py defines no `save_config` — [base_connection.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/base_connection.py), [juniper.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/juniper/juniper.py)
- arista.py and aruba_aoscx.py define no `save_config` — [arista.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/arista/arista.py), [aruba_aoscx.py](https://github.com/ktbyers/netmiko/blob/develop/netmiko/aruba/aruba_aoscx.py)

### Inferences
- `save_config()` is called from exec mode. If called while still in a config session on Arista, `copy running-config startup-config` inside `(config-s-…)#` may be rejected or unavailable. Exit or commit the session first.
- The driver interface's `save_command()` should return `"copy running-config startup-config"` (or `"write memory"`) for EOS and AOS-CX, and `None` for Junos, where commit is the save.
- The engine can call `conn.save_config()` for EOS and AOS-CX. It must never call `save_config()` for Junos, because that raises `NotImplementedError`.

### Gaps
- Whether `save_config()` on AOS-CX ever produces a confirmation prompt (which would need `confirm=True`) is not documented in the sources found. Lab-test it.
