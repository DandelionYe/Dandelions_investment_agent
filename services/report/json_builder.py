import json
from pathlib import Path


def save_json_result(result: dict, output_dir: str = "storage/reports") -> str:
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    output_path = Path(output_dir) / f'{result["symbol"]}_result.json'

    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return str(output_path)