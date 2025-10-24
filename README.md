Comandos a ejecutar para desplegar la web:

# INSTALACIÓN NORMAL

```bash
pip install -r requirements.txt
python3 app.py
```

En caso de estar en linux primero crear un entorno virtual:

```bash
python3 -m venv librerias
source librerias/bin/activate
python3 app.py
```

## DOCKER

Para desplegar la web con docker, se deben ejecutar los siguiente comandos:

```bash
docker build --tag app:latest .
docker run -d --network=host app:latest
```

Y después visitamos el localhost por el puerto 5000
