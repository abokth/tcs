environment:
	test -d .env || virtualenv --no-site-packages .env
requires:
	. .env/bin/activate && pip install -r pip-requires.txt

