default:
    @just --list

test:
    python3 -m pytest tests/ -v

install:
    ./install.sh
