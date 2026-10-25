"""Development entry point (`python run.py`). Production servers can use `run:app`."""
from app import config, create_app

app = create_app()


def main():
    app.run(debug=config.DEBUG, host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
