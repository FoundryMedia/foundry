import click


def success(msg: str) -> None:
    click.secho(msg, fg="green", bold=True)


def info(msg: str) -> None:
    click.secho(msg, fg="blue", bold=True)


def warn(msg: str) -> None:
    click.secho(msg, fg="yellow", bold=True)


def error(msg: str) -> None:
    click.secho(msg, fg="red", bold=True)