---
layout: default
title: emodul — AI-driven heating control for TECH Sterowniki
description: Lokalne CLI i serwer MCP do sterowania ogrzewaniem podłogowym TECH Sterowniki / eModul.pl z poziomu Claude Desktop, Cursor, Claude Code i innych asystentów AI.
---

# emodul

**Steruj swoim ogrzewaniem TECH głosem AI — po polsku.**

`emodul` to nieoficjalne CLI + serwer MCP dla chmury **eModul.pl** używanej przez polskie sterowniki TECH Sterowniki (L-4X WIFI, L-8, L-9, L-12). Zainstaluj jednym poleceniem, podłącz pod swojego ulubionego asystenta AI, i mów do ogrzewania normalnym językiem.

> *„Ustaw Salon na 21.5"* — i tyle.

[Zainstaluj](#install){: .btn .btn-primary} [Zobacz na GitHubie](https://github.com/hculap/emodul){: .btn} [PyPI](https://pypi.org/project/emodul/){: .btn}

---

## Co potrafi

- **16 narzędzi MCP** — odczyt stref, ustawianie temperatury, harmonogramy, audyt konfiguracji, historia alarmów
- **3 drogi użycia** — chat klient z MCP (Claude Desktop, Cursor, Continue, Cline, Zed), CLI agent (Claude Code, Codex CLI), albo zwykła linia poleceń
- **Sterowanie strefami** — `set-temp`, `boost N min`, `on/off`, podpięcie do harmonogramu (5 slotów per sterownik)
- **Tłumaczenie polskie** — menu serwisowe, alarmy, statusy automatycznie po polsku (lokalna cache ~750 KB)
- **Audyt** — wykrywa złe wartości, drift między sterownikami, sugeruje poprawki
- **Background watcher** — SQLite-owy logger zmian relay/zone z auto-startem (launchd / systemd)
- **Auth z auto-odświeżaniem** — JWT w configu, hasło w keychain macOS/Linux/Windows, sam się reaktywuje po 401
- **Browser login** — hasło wpisujesz w lokalnym formularzu, agent AI nigdy go nie widzi

---

## Install

Wymaga Pythona 3.10+. Polecam `pipx`:

```bash
pipx install emodul
emodul auth login --browser     # one-time logowanie przez przeglądarkę
emodul install --all            # konfiguruje Claude Code + Claude Desktop
```

Po `emodul install --all`:

- `~/.claude/skills/emodul/SKILL.md` — Claude Code auto-discoveruje skill
- `~/.claude/skills/emodul-mcp/SKILL.md` — MCP-flavored skill dla chat klientów
- `mcpServers.emodul` w `claude_desktop_config.json` (z timestamped backup)

Restart Claude Desktop (⌘+Q) → gotowe.

[Pełna instrukcja w README](https://github.com/hculap/emodul#install){: .btn .btn-primary}

---

## Trzy drogi użycia

| Droga | Dla | Co dostajesz |
|---|---|---|
| **A: MCP server** | Claude Desktop · Cursor chat · Continue · Cline · Zed · JetBrains AI · OpenCode · Gemini CLI | Jeden `pipx install emodul` + wpis w configu klienta. Agent woła `get_status`, `set_zone_temperature` etc. jako natywne tools. |
| **B: CLI-agent skill** | Claude Code · Codex CLI · Cursor agent · Aider | Wklejasz URL do `AGENT.md` — agent sam się instaluje, autoryzuje i bierze do roboty. |
| **C: Sandbox fallback** | claude.ai web · ChatGPT web · Cowork | Agent w sandboxie wypisze ci komendy — uruchamiasz w swoim terminalu. |

[AGENT.md — full guide per runtime](https://github.com/hculap/emodul/blob/main/AGENT.md){: .btn}

---

## Przykładowe zapytania

W Claude Desktop / Cursor chat / dowolnym kliencie MCP:

> *„Pokaż mi temperatury we wszystkich strefach"* → `list_zones(all_modules=true)`

> *„Ustaw Łazienkę na 22 na 90 minut"* → `boost_zone(zone="Łazienka", celsius=22, minutes=90)`

> *„Sprawdź czy moje ogrzewanie jest dobrze ustawione"* → `audit_settings` + podsumowanie znalezisk

> *„Wyłącz wszystkie strefy na piętrze"* → `list_zones` → seria `toggle_zone(on=false)`

> *„Pokaż mi historię temperatury Salonu z ostatniego tygodnia"* → `get_temperature_history(zone="Salon", period="week")`

---

## Bezpieczeństwo

- **Hasło nigdy nie dociera do agenta AI**. W browser flow wpisujesz je w lokalnym formularzu (127.0.0.1) który POST-uje bezpośrednio do `emodul.pl`.
- JWT w `~/.config/emodul/config.json` (chmod 600). Hasło w keychain (macOS / Linux gnome-keyring / Windows Credential Manager).
- Auto-refresh tokena na 401 bez user interaction (przy zapisanym haśle).
- Wszystkie endpointy walidowane przez Pydantic + httpx; PIN-y menu serwisowego (5162 dla TECH) nie pokazują się w `--json` outputach.

---

## Dlaczego nie HACS / Home Assistant?

[`tech-controllers`](https://github.com/mariusz-ostoja-swierczynski/tech-controllers) (HACS integration) jest świetne, jeśli ma siedzieć w twoim Home Assistant ekosystemie. `emodul` celuje gdzie indziej:

- **AI-first** — primary surface to MCP tools dla agentów, nie YAML automations
- **Polish menu decoding** — z fabryczną cache `pl` 16k entries, działa od pierwszej minuty
- **Audit** — żaden inny klient nie sprawdza konfiguracji pod kątem typowych błędów
- **Background watcher** — logger SQLite niezależny od jakiegokolwiek HA setupu

Możesz mieć obie rzeczy zainstalowane jednocześnie — emodul nie pisze do API w sposób który zaburza HA integration.

---

## Stack

`click` · `httpx` · `rich` · `keyring` · `mcp[cli]` · `anyio` · `hatchling`

Python 3.10 / 3.11 / 3.12 / 3.13 · macOS · Linux · Windows (community-tested)

---

## Status

Beta. Działa na produkcji autora od kwietnia 2026 (2 sterowniki, 8 stref). API eModul.pl jest niepublikowane i może się zmienić bez zapowiedzi — w razie awarii zgłoś [issue](https://github.com/hculap/emodul/issues).

[CHANGELOG](https://github.com/hculap/emodul/blob/main/CHANGELOG.md) · [Discussions](https://github.com/hculap/emodul/discussions) · [Issues](https://github.com/hculap/emodul/issues)
