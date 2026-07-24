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
    assert finding.finding_id.startswith("partial-fingerprints:")
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
    assert finding.finding_id == "src/module.py::lint_fix::f401::line-3::import-module-unus"
    assert finding.source_metadata is not None
    assert finding.source_metadata.native_id is None
    assert finding.severity == "high"


def test_collect_artifact_findings_defaults_missing_level_to_medium(
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

    assert result.findings[0].severity == "medium"


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
    assert result.metadata.managed_source_ids == ["codeql-sarif"]
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

    assert result.findings[0].finding_id != result.findings[1].finding_id
    assert result.findings[0].finding_id.startswith("partial-fingerprints:")
    assert result.findings[1].finding_id.startswith("partial-fingerprints:")


def test_collect_artifact_findings_scopes_partial_fingerprints_by_result_context(
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
                    },
                    {
                      "id": "F401",
                      "shortDescription": {"text": "Unused import"}
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
                    "primaryLocationLineHash": "shared-fingerprint"
                  }
                },
                {
                  "ruleId": "F401",
                  "level": "warning",
                  "message": {"text": "Second result"},
                  "locations": [
                    {
                      "physicalLocation": {
                        "artifactLocation": {"uri": "src/other.py"},
                        "region": {"startLine": 8}
                      }
                    }
                  ],
                  "partialFingerprints": {
                    "primaryLocationLineHash": "shared-fingerprint"
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

    assert result.findings[0].finding_id != result.findings[1].finding_id


def test_collect_artifact_findings_fingerprint_identity_is_order_independent(
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
                  "fingerprints": {
                    "beta": "value-b",
                    "alpha": "value-a"
                  }
                },
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
                  "fingerprints": {
                    "alpha": "value-a",
                    "beta": "value-b"
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

    assert result.findings[0].finding_id == result.findings[1].finding_id


def test_collect_artifact_findings_scopes_full_fingerprints_by_result_context(
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
                    },
                    {
                      "id": "F401",
                      "shortDescription": {"text": "Unused import"}
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
                  "fingerprints": {
                    "shared": "same-value"
                  }
                },
                {
                  "ruleId": "F401",
                  "level": "warning",
                  "message": {"text": "Second result"},
                  "locations": [
                    {
                      "physicalLocation": {
                        "artifactLocation": {"uri": "src/other.py"},
                        "region": {"startLine": 8}
                      }
                    }
                  ],
                  "fingerprints": {
                    "shared": "same-value"
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

    assert result.findings[0].finding_id != result.findings[1].finding_id


def test_collect_artifact_findings_fallback_identity_uses_result_specific_content(
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
                  "message": {"text": "First result wording"},
                  "locations": [
                    {
                      "physicalLocation": {
                        "artifactLocation": {"uri": "src/service.py"},
                        "region": {"startLine": 42}
                      }
                    }
                  ]
                },
                {
                  "ruleId": "E712",
                  "level": "warning",
                  "message": {"text": "Second result wording"},
                  "locations": [
                    {
                      "physicalLocation": {
                        "artifactLocation": {"uri": "src/service.py"},
                        "region": {"startLine": 42}
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

    assert result.findings[0].finding_id != result.findings[1].finding_id


def test_collect_artifact_findings_fallback_identity_uses_region_columns(
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
                  "message": {"text": "Repeated result wording"},
                  "locations": [
                    {
                      "physicalLocation": {
                        "artifactLocation": {"uri": "src/service.py"},
                        "region": {"startLine": 42, "startColumn": 3}
                      }
                    }
                  ]
                },
                {
                  "ruleId": "E712",
                  "level": "warning",
                  "message": {"text": "Repeated result wording"},
                  "locations": [
                    {
                      "physicalLocation": {
                        "artifactLocation": {"uri": "src/service.py"},
                        "region": {"startLine": 42, "startColumn": 9}
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

    assert result.findings[0].finding_id != result.findings[1].finding_id


def test_collect_artifact_findings_fallback_identity_uses_same_line_end_column(
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
                  "message": {"text": "Repeated result wording"},
                  "locations": [
                    {
                      "physicalLocation": {
                        "artifactLocation": {"uri": "src/service.py"},
                        "region": {"startLine": 42, "startColumn": 3, "endColumn": 8}
                      }
                    }
                  ]
                },
                {
                  "ruleId": "E712",
                  "level": "warning",
                  "message": {"text": "Repeated result wording"},
                  "locations": [
                    {
                      "physicalLocation": {
                        "artifactLocation": {"uri": "src/service.py"},
                        "region": {"startLine": 42, "startColumn": 3, "endColumn": 20}
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

    assert result.findings[0].finding_id != result.findings[1].finding_id


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
    assert result.metadata.managed_source_ids == []
    assert result.metadata.statistics == {"collected": 0, "skipped": 1}


def test_collect_artifact_findings_decodes_percent_encoded_relative_paths(
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
                  "message": {"text": "Encoded path"},
                  "locations": [
                    {
                      "physicalLocation": {
                        "artifactLocation": {"uri": "src/my%20file.py"},
                        "region": {"startLine": 5}
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

    assert result.findings[0].repository_path == "src/my file.py"


def test_collect_artifact_findings_accepts_file_uri_inside_repo_root(tmp_path: Path) -> None:
    repo_root = tmp_path
    artifact = repo_root / "ruff.sarif"
    target = repo_root / "samples" / "ruff_findings" / "boolean_comparison.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("return flag == True\n", encoding="utf-8")
    artifact.write_text(
        f"""
        {{
          "version": "2.1.0",
          "runs": [
            {{
              "tool": {{
                "driver": {{
                  "name": "Ruff",
                  "rules": [
                    {{
                      "id": "E712",
                      "shortDescription": {{"text": "Avoid equality comparisons to True"}}
                    }}
                  ]
                }}
              }},
              "results": [
                {{
                  "ruleId": "E712",
                  "level": "warning",
                  "message": {{"text": "Boolean equality"}},
                  "locations": [
                    {{
                      "physicalLocation": {{
                        "artifactLocation": {{"uri": "file://{target.resolve().as_posix()}"}},
                        "region": {{"startLine": 1}}
                      }}
                    }}
                  ]
                }}
              ]
            }}
          ]
        }}
        """.strip(),
        encoding="utf-8",
    )

    result = SarifFindingSource(repo_root=repo_root).collect_artifact_findings(artifact)

    assert result.findings[0].repository_path == "samples/ruff_findings/boolean_comparison.py"


def test_collect_artifact_findings_rejects_file_uri_outside_repo_root(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    artifact = repo_root / "ruff.sarif"
    outside = tmp_path / "outside.py"
    outside.write_text("return flag == True\n", encoding="utf-8")
    artifact.write_text(
        f"""
        {{
          "version": "2.1.0",
          "runs": [
            {{
              "tool": {{
                "driver": {{
                  "name": "Ruff"
                }}
              }},
              "results": [
                {{
                  "ruleId": "E712",
                  "level": "warning",
                  "message": {{"text": "Outside path"}},
                  "locations": [
                    {{
                      "physicalLocation": {{
                        "artifactLocation": {{"uri": "file://{outside.resolve().as_posix()}"}},
                        "region": {{"startLine": 1}}
                      }}
                    }}
                  ]
                }}
              ]
            }}
          ]
        }}
        """.strip(),
        encoding="utf-8",
    )

    result = SarifFindingSource(repo_root=repo_root).collect_artifact_findings(artifact)

    assert result.findings == []


def test_collect_artifact_findings_keeps_all_run_source_ids_for_mixed_tool_artifact(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "mixed.sarif"
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
              "results": []
            },
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

    assert result.metadata.source_id == "sarif"
    assert result.metadata.managed_source_ids == ["codeql-sarif", "ruff-sarif"]


def test_collect_artifact_findings_keeps_fallback_managed_source_for_empty_artifact(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "ruff.sarif"
    artifact.write_text(
        """
        {
          "version": "2.1.0",
          "runs": []
        }
        """.strip(),
        encoding="utf-8",
    )

    result = SarifFindingSource().collect_artifact_findings(artifact)

    assert result.findings == []
    assert result.metadata.source_id == "ruff-sarif"
    assert result.metadata.managed_source_ids == ["ruff-sarif"]
