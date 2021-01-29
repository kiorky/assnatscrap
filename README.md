# install
```sh
cp .env.dist .env
$EDITOR .env
set -a;source .env;set +a
docker-compose build
```

# run
```sh
APP_UID=$(id -u) APP_GID=$(id -g) docker-compose run --rm -e LAWID=41074 scrap
./scrap.py
```

- Think to remove anything inside `data/law/$id` when the law changes stage (rooms from Commission to AN, to Sénat) as the amendements may be renumbered invalidating the data cache !

(export will be inside `data/*xls`)

## Find law id
- Go to https://data.assemblee-nationale.fr/dossierLeg/liste-amendements
- select your law
- extract id and repo from URL  (or get them via looking the request when you download them manually)

