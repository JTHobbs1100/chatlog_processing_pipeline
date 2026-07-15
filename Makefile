UV ?= uv

.PHONY: init pyfmt pylint smoke

init:
	$(UV) sync --all-groups

pyfmt:
	$(UV) run isort --profile black src
	$(UV) run black src

pylint:
	$(UV) run pylint src

smoke:
	$(UV) run process_chats --help >/dev/null
	$(UV) run process_chats_plan --help >/dev/null
	$(UV) run format_chats_html --help >/dev/null
	$(UV) run find_duplicate_contents --help >/dev/null
