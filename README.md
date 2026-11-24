# awg-ctl

[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)]()
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)]()
[![Build](https://img.shields.io/badge/build-passing-brightgreen.svg)]()
[![Status](https://img.shields.io/badge/status-Alpha-orange.svg)]()

> **⚠️ Альфа-версия**
> `v0.1.0`. Software in active development. API, commands and config format may change without backward compatibility.
> Use for testing and feedback. Not for production.

**awg-ctl** — CLI-утилита для управления 3-серверным каскадом AmneziaWG (WireGuard).
Предназначена для диагностики, аудита keepalive/handshake, E2E-проверки IP и интерактивного мониторинга состояния туннелей.

---

## ✨ Особенности

- **Полная диагностика каскада** — опрос `awg show all dump` на 3 узлах (in / mid / out) по SSH
- **Аудит keepalive / handshake** — валидация `persistent_keepalive` в диапазоне, детект passive-keepalive на приёмном конце
- **E2E IP-проба** — `curl` к `ip_checker_url` через каскад, результат в отчёте
- **Светофорный обзор** — команда `now` с интерактивной таблицей статусов (🟢/🟡/🔴)
- **Пер-серверные SSH-ключи** — `ssh_key_path` в конфиге для каждого узла, поддержка passphrase
- **Три схемы exit-кодов** — Nagios (default), Unix, Unix+warn-as-ok; флаги `--strict`, `--legacy-until`
- **JSON-схема v1/v2** — машиночитаемые отчёты для CI/CD интеграции
- **Безопасность** — RejectPolicy для host keys, редактирование секретов в логах, отсутствие секретов в конфиге

---

## 📦 Установка

### Требования
- Python 3.11+
- SSH-доступ к трём серверам каскада (key-based auth)
- `curl` на контроллере (для E2E-пробы)

### Установка пакета
```bash
# Из исходников
git clone https://github.com/oleg1981ekb-ai/net-doctor-k3.git
cd net-doctor-k3
pip install .

# Или в development-режиме
pip install -e .
```

После установки доступна команда `awg-ctl` (и `python -m awg_cascade_ctl`).

---

## 🚀 Быстрый старт (5 шагов)

```bash
# 1. Скопируйте пример конфига
cp examples/cascade.yaml.dist cascade.yaml

# 2. Отредактируйте cascade.yaml — впишите реальные хосты, подсети, порты
#    vim cascade.yaml

# 3. Сгенерируйте SSH-ключ для awg-ctl
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_awg -N ""

# 4. Раскидайте публичный ключ на все 3 узла
ssh-copy-id -i ~/.ssh/id_ed25519_awg root@vpn-in.example.com
ssh-copy-id -i ~/.ssh/id_ed25519_awg root@vpn-mid.example.com
ssh-copy-id -i ~/.ssh/id_ed25519_awg root@vpn-out.example.com

# 5. Заполните known_hosts (host key verification — RejectPolicy)
ssh-keyscan -H vpn-in.example.com  >> ~/.ssh/known_hosts
ssh-keyscan -H vpn-mid.example.com >> ~/.ssh/known_hosts
ssh-keyscan -H vpn-out.example.com >> ~/.ssh/known_hosts

# Права доступа
chmod 600 cascade.yaml ~/.ssh/id_ed25519_awg
chmod 700 ~/.ssh

# Проверка
awg-ctl check --config cascade.yaml
```

---

## ⚙️ Конфигурация

### Приоритет источников (от высшего к низшему)
| Приоритет | Источник | Пример |
|-----------|----------|--------|
| 1 | `--config <path>` | `awg-ctl check --config /etc/awg-ctl/cascade.yaml` |
| 2 | `AWG_CTL_CONFIG` env | `export AWG_CTL_CONFIG=/etc/awg-ctl/cascade.yaml` |
| 3 | `./cascade.yaml` (cwd) | `awg-ctl check` из корня проекта |
| 4 | `/etc/awg-ctl/cascade.yaml` | Системная установка |

### Структура `cascade.yaml`
```yaml
servers:
  in:
    host: "vpn-in.example.com"
    port: 22
    username: "root"
    ssh_key_path: "~/.ssh/id_ed25519_in"   # опционально
  mid:
    host: "vpn-mid.example.com"
    ...
  out:
    host: "vpn-out.example.com"
    ...

network:
  client_subnet: 10.9.9.0/24
  link1_subnet: 10.10.1.0/30
  link2_subnet: 10.10.2.0/30
  mtu: 1360
  mss_clamp: true
  persistent_keepalive: 33
  dns: [1.1.1.1, 9.9.9.9]
  ip_checker_url: "https://api.ipify.org"

check:
  keepalive_min: 1
  keepalive_max: 33
```

> **Секреты** (пароли, приватные ключи, токены) в `cascade.yaml` **не хранятся**.
> Пути к SSH-ключам указываются через `ssh_key_path`; passphrase — через `--ask-pass`, env `SSH_KEY_PASSPHRASE` или интерактивный prompt.

### Валидация
```bash
awg-ctl config validate -c cascade.yaml
# OK: cascade.yaml is valid
```

---

## 📋 Команды

| Команда | Назначение | Ключевые флаги |
|---------|------------|----------------|
| `version` | Версия утилиты | — |
| `check` | Полная проверка каскада + E2E | `-c/--config`, `-s/--server`, `--json`, `-v/--verbose`, `--schema v1\|v2`, `--exit-unix`, `--warn-as-ok`, `--strict`, `--dump-file`, `--key-path`, `--key-passphrase`, `--ask-pass` |
| `schema` | Вывод JSON Schema отчёта | `--json` |
| `diagnose` | Read-only диагностика узла | `-c/--config`, `-s/--server in\|mid\|out`, `--details`, `--json`, `--legacy-until`, `--exit-unix`, `--warn-as-ok`, `--strict`, `--ask-pass` |
| `now` | Интерактивный светофорный обзор (TTY) | `-c/--config` (default `./cascade.yaml`), `--ask-pass` (default `True`), `--key-path`, `--key-passphrase` |
| `menu` | Интерактивное меню (TTY) | `-c/--config`, `-k/--key-path`, `--ask-pass` |
| `deploy` | Развёртывание каскада (Phase 2) | `--dry-run` |
| `swap-exit` | Смена exit-узла (Phase 2) | `--new-host` |
| `test-failover` | Тест фейловера (Phase 2) | `--target`, `--wait-healthcheck` |
| `clients` | Управление клиентами (Phase 2) | — |
| `config validate` | Валидация конфига | `-c/--config` |

> Phase 2 команды (`deploy`, `swap-exit`, `test-failover`, `clients`) — стабы, выходят с кодом 64.

---

## 🖥 Примеры вывода

### `check` — текстовый отчёт
```bash
$ awg-ctl check --config cascade.yaml
awg-ctl check - cascade-alpha
status: PASS (pass)
overall: OK
generated_at: 2026-11-23T19:45:12+00:00

Links:
  2/2 ok
  awg0 -> 10.10.1.1:51821: keepalive=OK, handshake=fresh, ok=yes
  awg1 -> 10.10.2.1:51822: keepalive=OK, handshake=fresh, ok=yes

E2E probes:
  1/1 ok
  awg-in (https://api.ipify.org): 203.0.113.42, ok=yes
```

### `now` — интерактивный светофор (TTY)
```bash
$ awg-ctl now --config cascade.yaml
awg-ctl now  [🟢 Overall]
┌──────┬──────────┬────────────┬───────┬──────────────────────────────┐
│ Pos  │ Server   │ Status     │ E2E   │ Links (ok/total)             │
├──────┼──────────┼────────────┼───────┼──────────────────────────────┤
│ 1    │ in       │ 🟢 PASS    │ 1/1   │ 1/1                          │
│ 2    │ mid      │ 🟢 PASS    │ 1/1   │ 1/1                          │
│ 3    │ out      │ 🟢 PASS    │ —     │ 1/1                          │
└──────┴──────────┴────────────┴───────┴──────────────────────────────┘
↑↓ select  enter details  c check  d diagnose  r refresh  q quit
```

### JSON (для CI)
```bash
$ awg-ctl check --config cascade.yaml --json --schema v2
{
  "schema": "awg-ctl/check/v1",
  "schema_version": "1.0",
  "generated_at": "2026-11-23T19:45:12+00:00",
  "cascade": "cascade-alpha",
  "links": [...],
  "e2e_probes": [...],
  "ok": true,
  "status": "pass",
  "source": "ssh"
}
```

---

## 🔢 Exit codes

### Схемы
| Флаг | Режим | `ok` / `pass` | `warn` / `warning` | `fail` / `critical` |
|------|-------|---------------|-------------------|---------------------|
| (нет) | **Nagios** (default) | 0 | 3 (`WARNING`) | 1 (`CRITICAL`) |
| `--exit-unix` | **Unix** | 0 | 1 | 1 |
| `--exit-unix --warn-as-ok` | **Unix + warn-as-ok** | 0 | 0 | 1 |

### Дополнительные флаги
- `--strict` — трактует `warn` как `fail` **до** маппинга схемы (в Nagios: warn→1 вместо 3)
- `--warn-as-ok` — в Unix схеме делает `warn` → exit 0 (взаимоисключение с `--strict`)
- `--legacy-until YYYY-MM-DD` — legacy-режим до даты включительно (stderr warning); после даты — usage error (exit 64)
- Usage errors (неверные флаги, Phase 2 стабы) → exit 64 (`EX_USAGE`)

---

## 🛠 Разработка

```bash
# Линт
make lint           # ruff check .

# Тесты
make test           # pytest -q

# AI-infrastructure smoke test (по регламенту)
make ai-smoke       # bash scripts/ai-smoke.sh

# Форматирование
ruff format .
```

Все проверки должны проходить с exit code 0 перед коммитом.

---

## 📚 Документация

- [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) — полное руководство по конфигурации
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — архитектура, схема команд, область ответственности
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — принятые архитектурные решения (ADR)
- [`SPEC/SPEC.md`](SPEC/SPEC.md) — процесс и спецификация
- [`SPEC/adr/`](SPEC/adr/) — Architecture Decision Records (ADR-001...ADR-005)
- [`examples/cascade.yaml.dist`](examples/cascade.yaml.dist) — пример конфигурации с комментариями

---

## 🔐 Безопасность

- `cascade.yaml` содержит реальную топологию инфраструктуры — относитесь к нему как к секрету
- **Никогда не коммитьте** `cascade.yaml` в VCS (см. `.gitignore`)
- `SSHTransport` использует `RejectPolicy` — неизвестные host keys **никогда** не доверяются автоматически
- Все удалённые команды через `SSHTransport` проходят редактирование секретов перед передачей/логированием
- SSH-аутентификация **только по ключам**; пароли не поддерживаются

---

## 📄 Лицензия

MIT License — см. файл [LICENSE](LICENSE) (если есть) или уточните у владельца репозитория.
