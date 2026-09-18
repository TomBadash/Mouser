PY := .venv/bin/python
APP := dist/Mouser.app

.PHONY: dev release run-release install test quit clean

$(PY): requirements.txt
	python3 -m venv .venv
	$(PY) -m pip install -r requirements.txt
	touch $(PY)

# Only one Mouser can own the mouse at a time.
quit:
	-pkill -x Mouser

dev: $(PY) quit
	$(PY) main_qml.py

release: $(PY)
	./build_macos_app.sh

run-release: release quit
	open $(APP)

# Replaces the installed copy; ditto preserves the bundle's signature.
install: release quit
	rm -rf /Applications/Mouser.app
	ditto $(APP) /Applications/Mouser.app
	open /Applications/Mouser.app

test: $(PY)
	$(PY) -m unittest discover -s tests

clean:
	rm -rf build dist
