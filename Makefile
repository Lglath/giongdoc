# GiongDoc developer tasks. Run `make help`.
# Pick Python 3.11+ (macOS's built-in python3 is 3.9 and does not work).
PYTHON ?= $(shell for c in python3.13 python3.12 python3.11 /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11 python3; do \
  command -v $$c >/dev/null 2>&1 && $$c -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null && { echo $$c; break; }; done)
VENV   ?= .venv
PY     := $(VENV)/bin/python

.PHONY: help venv run test icon icns build dmg clean distclean

help:
	@echo "make venv   - create $(VENV) and install requirements"
	@echo "make run    - run the app from source"
	@echo "make test   - run pytest"
	@echo "make icon   - regenerate packaging/assets/icon_1024.png"
	@echo "make icns   - build GiongDoc.icns (macOS)"
	@echo "make build  - build dist/GiongDoc.app (macOS, no DMG)"
	@echo "make dmg    - full build: .app + signed + dist/GiongDoc-<ver>-<arch>.dmg"
	@echo "make clean  - remove build artefacts"

$(PY):
	@test -n "$(PYTHON)" || { echo 'Can Python 3.11+: chay  brew install python@3.11  roi thu lai'; exit 1; }
	@echo "Dung $(PYTHON)"
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt pytest

venv: $(PY)

run: $(PY)
	$(PY) run.py

test: $(PY)
	$(PY) -m pytest -q tests

icon:
	$(PYTHON) packaging/make_icon.py

icns: icon
	bash packaging/make_icns.sh

build:
	SKIP_DMG=1 bash packaging/build_macos.sh

dmg:
	bash packaging/build_macos.sh

clean:
	rm -rf build dist packaging/build packaging/vendor .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

distclean: clean
	rm -rf $(VENV) .venv-build
