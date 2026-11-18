.PHONY: install all sql test
install:
	pip install -r requirements.txt
all:
	python -m src.pipeline
sql:
	python -m src.run_sql
test:
	python -m pytest -q
