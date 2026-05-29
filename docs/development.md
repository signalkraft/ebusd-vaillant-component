# Set up a Development Environment

A `docker-compose.yml` is provided to spin up a test Home Assistant instance
with the component pre-installed.

1. Copy the environment template:
   ```bash
   cp docker/.env.sample docker/.env
   ```
2. Edit `docker/.env` and set your MQTT broker address and port. ebusd needs to be running and publishing already; it's not included in this setup.
3. Start the container:
   ```bash
   docker compose up -d
   ```
4. Access Home Assistant at [http://localhost:8123](http://localhost:8123) and log in with `test` / `test`.
5. You should find [devices in the integration](https://my.home-assistant.io/redirect/integration/?domain=ebusd_vaillant).

## Pre-commit

This repository uses [pre-commit](https://pre-commit.com/) to run linting, formatting, and consistency checks.

Install the hooks:

```bash
uv tool install pre-commit --with pre-commit-uv
pre-commit install
```

Once installed, checks run automatically on every `git commit`. You can also run them manually:

```bash
pre-commit run --all-files
```

## Running tests

Tests use [pytest](https://docs.pytest.org/) with `pytest-homeassistant-custom-component`.

Run all tests:

```bash
uv run pytest
```

Or run a specific test file:

```bash
uv run pytest tests/test_climate.py -v
```
