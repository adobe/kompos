from pathlib import Path


def mutate(inputs, context):
    directory = Path(context["config_path"]).resolve().parent
    return {
        "body": {"source": f"{inputs['source']}-changed"},
        "write_path": str(directory / "generated.yaml"),
    }
