from main import build_parser


def test_cli_use_graph_flag_defaults_to_false():
    args = build_parser().parse_args([])

    assert args.use_graph is False


def test_cli_use_graph_flag_can_be_enabled():
    args = build_parser().parse_args(["--use-graph"])

    assert args.use_graph is True


def test_cli_pdf_flag_defaults_to_false():
    args = build_parser().parse_args([])

    assert args.pdf is False


def test_cli_pdf_flag_can_be_enabled():
    args = build_parser().parse_args(["--pdf"])

    assert args.pdf is True
