PREFIX ?= $(HOME)/.local
.PHONY: test install
test:
	python3 -m unittest discover -s tests -v
install:
	install -d "$(DESTDIR)$(PREFIX)/bin"
	install -m 755 bin/shell-lock "$(DESTDIR)$(PREFIX)/bin/shell-lock"
