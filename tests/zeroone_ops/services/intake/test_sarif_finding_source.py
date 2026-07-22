from pathlib import Path

from zeroone_ops.services.intake.sarif_finding_source import SarifFindingSource


def test_collect_artifact_findings_normalizes_ruff_sarif_results(tmp_path: Path) -> None:
    artifact = tmp_path / "ruff.sarif"
    artifact.write_text(
        """
        {
          "version": "2.1.0",
          "runs": [
            {
              "tool": {
                "driver": {
                  "name": "Ruff",
                  "rules": [
                    {
                      "id": "E712",
                      "name": "true-false-comparison",
                      "shortDescription": {"text": "Avoid equality comparisons to True"},
                      "helpUri": "https://docs.astral.sh/ruff/rules/true-false-comparison/"
                    }
                  ]
                }
              },
              "results": [
                {
                  "ruleId": "E712",
                  "level": "warning",
                  "message": {
                    "text": "Avoid equality comparisons to `True`; use `flag:` for truth checks"
                  },
                  "locations": [
                    {
                      "physicalLocation": {
                        "artifactLocation": {"uri": "src/service.py"},
                        "region": {"startLine": 42, "endLine": 42}
                      }
                    }
                  ],
                  "partialFingerprints": {
                    "primaryLocationLineHash": "line-hash-1"
                  }
                }
              ]
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    result = SarifFindingSource().collect_artifact_findings(artifact)

    assert result.metadata.source_id == "ruff-sarif"
    assert result.metadata.artifact_reference == str(artifact)
    assert result.metadata.statistics == {"collected": 1, "skipped": 0}
    finding = result.findings[0]
    assert finding.finding_id == "line-hash-1"
    assert finding.source_id == "ruff-sarif"
    assert finding.severity == "medium"
    assert finding.title == "Avoid equality comparisons to True"
    assert finding.summary.startswith("Avoid equality comparisons")
    assert finding.repository_path == "src/service.py"
    assert finding.line_start == 42
    assert finding.line_end == 42
    assert finding.remediation_context.category == "lint_fix"
    assert finding.remediation_context.diagnostic_code == "E712"
    assert finding.source_metadata is not None
    assert finding.source_metadata.native_id == "line-hash-1"
    assert finding.source_metadata.source_url is not None


def test_collect_artifact_findings_uses_fallback_identity_without_native_key(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "ruff.sarif"
    artifact.write_text(
        """
        {
          "version": "2.1.0",
          "runs": [
            {
              "tool": {
                "driver": {
                  "name": "Ruff",
                  "rules": [
                    {
                      "id": "F401",
                      "shortDescription": {"text": "Unused import"}
                    }
                  ]
                }
              },
              "results": [
                {
                  "ruleId": "F401",
                  "level": "error",
                  "message": {"text": "module imported but unused"},
                  "locations": [
                    {
                      "physicalLocation": {
                        "artifactLocation": {"uri": "src/module.py"},
                        "region": {"startLine": 3}
                      }
                    }
                  ]
                }
              ]
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    result = SarifFindingSource().collect_artifact_findings(artifact)

    finding = result.findings[0]
    assert finding.finding_id == "src/module.py::lint_fix::f401::line-3"
    assert finding.source_metadata is not None
    assert finding.source_metadata.native_id is None
    assert finding.severity == "high"


def test_collect_artifact_findings_derives_source_id_from_sarif_tool_name(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "codeql.sarif"
    artifact.write_text(
        """
        {
          "version": "2.1.0",
          "runs": [
            {
              "tool": {
                "driver": {
                  "name": "CodeQL",
                  "rules": [
                    {
                      "id": "py/path-injection",
                      "shortDescription": {"text": "Path injection"}
                    }
                  ]
                }
              },
              "results": [
                {
                  "ruleId": "py/path-injection",
                  "level": "error",
                  "message": {"text": "Potential path injection."},
                  "locations": [
                    {
                      "physicalLocation": {
                        "artifactLocation": {"uri": "src/module.py"},
                        "region": {"startLine": 8}
                      }
                    }
                  ]
                }
              ]
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    result = SarifFindingSource().collect_artifact_findings(artifact)

    assert result.metadata.source_id == "codeql-sarif"
    assert result.findings[0].source_id == "codeql-sarif"


def test_collect_artifact_findings_uses_fingerprints_to_distinguish_same_location_results(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "ruff.sarif"
    artifact.write_text(
        """
        {
          "version": "2.1.0",
          "runs": [
            {
              "tool": {
                "driver": {
                  "name": "Ruff",
                  "rules": [
                    {
                      "id": "E712",
                      "shortDescription": {"text": "Avoid equality comparisons to True"}
                    }
                  ]
                }
              },
              "results": [
                {
                  "ruleId": "E712",
                  "level": "warning",
                  "message": {"text": "First result"},
                  "locations": [
                    {
                      "physicalLocation": {
                        "artifactLocation": {"uri": "src/service.py"},
                        "region": {"startLine": 42}
                      }
                    }
                  ],
                  "partialFingerprints": {
                    "primaryLocationLineHash": "fingerprint-1"
                  }
                },
                {
                  "ruleId": "E712",
                  "level": "warning",
                  "message": {"text": "Second result"},
                  "locations": [
                    {
                      "physicalLocation": {
                        "artifactLocation": {"uri": "src/service.py"},
                        "region": {"startLine": 42}
                      }
                    }
                  ],
                  "partialFingerprints": {
                    "primaryLocationLineHash": "fingerprint-2"
                  }
                }
              ]
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    result = SarifFindingSource().collect_artifact_findings(artifact)

    assert [finding.finding_id for finding in result.findings] == [
        "fingerprint-1",
        "fingerprint-2",
    ]


def test_collect_artifact_findings_skips_results_without_repository_path(tmp_path: Path) -> None:
    artifact = tmp_path / "ruff.sarif"
    artifact.write_text(
        """
        {
          "version": "2.1.0",
          "runs": [
            {
              "tool": {
                "driver": {
                  "name": "Ruff"
                }
              },
              "results": [
                {
                  "ruleId": "E999",
                  "level": "error",
                  "message": {"text": "Missing path"}
                }
              ]
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    result = SarifFindingSource().collect_artifact_findings(artifact)

    assert result.findings == []
    assert result.metadata.statistics == {"collected": 0, "skipped": 1}
    assert result.metadata.warnings == [
        "Skipped SARIF result E999 because no repository-relative path was found."
    ]


def test_collect_artifact_findings_rejects_parent_traversal_paths(tmp_path: Path) -> None:
    artifact = tmp_path / "ruff.sarif"
    artifact.write_text(
        """
        {
          "version": "2.1.0",
          "runs": [
            {
              "tool": {
                "driver": {
                  "name": "Ruff"
                }
              },
              "results": [
                {
                  "ruleId": "E712",
                  "level": "warning",
                  "message": {"text": "Bad path"},
                  "locations": [
                    {
                      "physicalLocation": {
                        "artifactLocation": {"uri": "../src/service.py"},
                        "region": {"startLine": 1}
                      }
                    }
                  ]
                }
              ]
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    result = SarifFindingSource().collect_artifact_findings(artifact)

    assert result.findings == []
    assert result.metadata.statistics == {"collected": 0, "skipped": 1}
