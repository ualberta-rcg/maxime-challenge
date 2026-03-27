from .handlers import setup_handlers

try:
    from ._version import __version__
except ImportError:
    __version__ = "dev"


def _jupyter_labextension_paths():
    return [{"src": "labextension", "dest": "jupyterlab-slurm-extend"}]


def _jupyter_server_extension_points():
    return [{"module": "jupyterlab_slurm_extend"}]


def _load_jupyter_server_extension(server_app):
    setup_handlers(server_app.web_app)
    server_app.log.info(
        "jupyterlab-slurm-extend server extension loaded (v%s)", __version__
    )
