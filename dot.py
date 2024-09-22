#!/usr/bin/env python3
"""
Manage links to dotfiles.
"""

__all__ = ["dot"]
__ALL__ = dir() + __all__

import logging
import os
import re
import sys
from argparse import ArgumentParser
from pathlib import Path
from string import Template


def __dir__():
    return __ALL__


def standardize(message, color=None):
    """
    Apply color and capitalize the first word of each line.
    """

    COLORS = {
        "blue": "\x1b[36;20m",
        "green": "\x1b[32;20m",
        "grey": "\x1b[38;20m",
        "red": "\x1b[31;20m",
        "red bold": "\x1b[31;1m",
        "reset": "\x1b[0m",
        "yellow": "\x1b[33;20m",
    }

    return (
        COLORS.get(color, COLORS["reset"])
        + "\n".join((m[0].upper() if len(m) > 0 else "") + (m[1:] if len(m) > 1 else "") for m in message.split("\n"))
        + COLORS.get(color, COLORS["reset"])
    )


def get_counting_logger(verbose):
    class ColoredFormatter(logging.Formatter):
        FORMAT = "%(message)s"
        formats = {
            logging.DEBUG: standardize(FORMAT, "grey"),
            logging.INFO: standardize(FORMAT, "green"),
            logging.WARNING: standardize(FORMAT, "yellow"),
            logging.ERROR: standardize(FORMAT, "red"),
            logging.CRITICAL: standardize(FORMAT, "red bold"),
        }

        def format(self, record):
            format = self.formats.get(record.levelno)
            record.msg = standardize(record.msg)
            return logging.Formatter(format).format(record)

    class CallCounter:
        def __init__(self, method):
            self.method = method
            self.counter = 0

        def __call__(self, *args, **kwargs):
            self.counter += 1
            return self.method(*args, **kwargs)

    if verbose == 0:
        level = logging.WARNING
    elif verbose == 1:
        level = logging.INFO
    else:
        level = logging.DEBUG

    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(ColoredFormatter())

    logger = logging.getLogger()
    logger.setLevel(level)
    logger.addHandler(handler)

    logger.warning = CallCounter(logger.warning)
    return logger


def render_link_recurse(*, candidate, dry_run, logger, **_):
    """
    Render templates recursively.
    """
    for subcandidate in sorted(candidate.glob("**/*.template")):
        if subcandidate.is_file():
            # NOTE file.template -> file.rendered -> file
            subname = subcandidate.name
            subrendered = subcandidate.parent / re.sub(".template$", ".rendered", subname)
            subdotfile = subcandidate.parent / re.sub(".template$", "", subname)
            render_single(candidate=subcandidate, rendered=subrendered, dry_run=dry_run, logger=logger)
            link(rendered=subrendered, dotfile=subdotfile, dry_run=dry_run, logger=logger)


def render_single(*, candidate, rendered, dry_run, logger, **_):
    """
    Render a template.
    """
    if candidate != rendered:
        if not dry_run:
            with open(candidate, "r", encoding="utf-8") as candidate_file:
                with open(rendered, "w", encoding="utf-8") as rendered_file:
                    content = Template(candidate_file.read()).safe_substitute(os.environ)
                    rendered_file.write(content)
        logger.info(f"File {rendered} created.")


def link(*, rendered, dotfile, dry_run, logger, **_):
    """
    Link dotfiles to files in given profile directories.
    """
    if not dotfile.exists():
        if not dry_run:
            dotfile.symlink_to(rendered)
        return logger.info(f"File {dotfile} created and linked to {rendered}")

    if not dotfile.is_symlink():
        return logger.warning(f"File {dotfile} exists but is not a link")

    dotfile_link = Path(os.readlink(str(dotfile))).expanduser().resolve()
    if dotfile_link != rendered:
        return logger.warning(f"File {dotfile} exists and points to {dotfile_link} instead of {rendered}")

    return logger.info(f"File {dotfile} links to {rendered} as expected")


def unlink(*, rendered, dotfile, dry_run, logger, **_):
    """
    Unlink dotfiles linked to files in given profile directories.
    """
    if not dotfile.exists():
        return logger.warning(f"File {dotfile} does not exists")

    if not dotfile.is_symlink():
        return logger.warning(f"File {dotfile} exists but is not a link")

    dotfile_link = Path(os.readlink(str(dotfile))).expanduser().resolve()
    if dotfile_link != rendered:
        return logger.warning(f"File {dotfile} exists and points to {dotfile_link} instead of {rendered}")

    if not dry_run:
        dotfile.unlink()
    return logger.info(f"File {dotfile} unlinked from {rendered}")


def run(command, home, profiles, dry_run, logger):
    home = Path(home).expanduser().resolve()
    if not home.is_dir():
        return logger.warning(f"Folder {home} does not exist")
    for profile in profiles:
        profile = Path(profile).expanduser().resolve()
        if not profile.is_dir():
            logger.warning(f"Profile {profile} does not exist")
            continue
        for candidate in sorted(profile.glob("*")):
            name = candidate.name
            if name.startswith(".") or (name.endswith(".rendered") and candidate.is_file()):
                logger.debug(f"File {candidate} ignored.")
                continue
            # Add dot prefix and replace template when needed
            if candidate.is_dir():
                rendered = candidate
                dotfile = home / ("." + name)
            else:
                # NOTE file.template -> file.rendered -> .file
                rendered = candidate.parent / re.sub(".template$", ".rendered", name)
                dotfile = home / ("." + re.sub(".template$", "", name))
            # Run user requested command
            for func in commands[command]:
                func(candidate=candidate, rendered=rendered, dotfile=dotfile, dry_run=dry_run, logger=logger)


def dot(command, home, profiles, dry_run, verbose):
    logger = get_counting_logger(verbose)
    run(command, home, profiles, True, logger)  # Dry run first

    if logger.warning.counter > 0:
        logger.error("Error: There were conflicts. Exiting without changing dotfiles.")
        raise SystemExit(1)

    if not dry_run:
        logger = get_counting_logger(0)
        run(command, home, profiles, dry_run, logger)  # Wet run second


def dot_from_args(*, prog="dot.py"):
    def parse_args(prog):
        class ColoredArgumentParser(ArgumentParser):
            def print_usage(self, file=None):
                if file is None:
                    file = sys.stdout
                self._print_message(standardize(self.format_usage(), "yellow"), file)

            def print_help(self, file=None):
                if file is None:
                    file = sys.stdout
                self._print_message(standardize(self.format_help()), file)

            def error(self, message):
                self.print_usage(sys.stderr)
                self.exit(2, standardize(f"Error: {self.prog}: {message.strip()}", "red") + "\n")

        parser = ColoredArgumentParser(prog=prog, description=__doc__)
        subparsers = parser.add_subparsers(dest="command", required=True)
        for key, funcs in commands.items():
            subparser = subparsers.add_parser(key, description=funcs[-1].__doc__)
            subparser.add_argument("profiles", nargs="+")
            subparser.add_argument("--home", nargs="?", default="~")
            subparser.add_argument("-v", "--verbose", action="count", default=0)
            subparser.add_argument("-d", "--dry-run", default=False, action="store_true")
            subparser.add_argument("--no-dry-run", dest="dry_run", action="store_false")
        return vars(parser.parse_args())

    dot(**parse_args(prog))


commands = {"link": [render_link_recurse, render_single, link], "unlink": [unlink]}

if __name__ == "__main__":
    dot_from_args(prog="dot")
