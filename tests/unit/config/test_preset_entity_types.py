"""Tests for entity type integration in presets."""
from __future__ import annotations

from bq_entity_resolution.config.presets import (
    business_dedup_preset,
    financial_transaction_preset,
    healthcare_patient_preset,
    insurance_dedup_preset,
    person_dedup_preset,
    quick_config,
)


class TestQuickConfigEntityType:
    def test_entity_type_none_by_default(self):
        config = quick_config(
            bq_project="proj",
            source_table="proj.ds.tbl",
            columns=["first_name", "last_name", "email"],
        )
        assert config.sources[0].entity_type is None

    def test_entity_type_set_when_provided(self):
        config = quick_config(
            bq_project="proj",
            source_table="proj.ds.tbl",
            columns=["first_name", "last_name", "email"],
            entity_type="Person",
        )
        assert config.sources[0].entity_type == "Person"

    def test_entity_type_propagates_to_source(self):
        config = quick_config(
            bq_project="proj",
            source_table="proj.ds.tbl",
            column_roles={"fname": "first_name", "lname": "last_name"},
            entity_type="Organization",
        )
        assert config.sources[0].entity_type == "Organization"

    def test_schema_org_columns_detected(self):
        """Columns with schema.org names are auto-detected as roles."""
        config = quick_config(
            bq_project="proj",
            source_table="proj.ds.tbl",
            columns=["givenName", "familyName", "email"],
            entity_type="Person",
        )
        # givenName and familyName should be detected via schema.org aliases
        role_map = {c.name: c.role for c in config.sources[0].columns}
        assert role_map.get("givenName") == "first_name"
        assert role_map.get("familyName") == "last_name"


class TestPresetEntityTypeFlow:
    def test_person_dedup_sets_entity_type(self):
        config = person_dedup_preset(
            bq_project="proj",
            source_table="proj.ds.tbl",
            columns={"first_name": "first_name", "last_name": "last_name"},
        )
        assert config.sources[0].entity_type == "Person"

    def test_business_dedup_sets_entity_type(self):
        config = business_dedup_preset(
            bq_project="proj",
            source_table="proj.ds.tbl",
            columns={"company_name": "company_name", "ein": "ein"},
        )
        assert config.sources[0].entity_type == "Organization"

    def test_insurance_dedup_sets_entity_type(self):
        config = insurance_dedup_preset(
            bq_project="proj",
            source_table="proj.ds.tbl",
            columns={
                "first_name": "first_name",
                "policy_number": "policy_number",
            },
        )
        assert config.sources[0].entity_type == "InsuredEntity"

    def test_financial_preset_sets_entity_type(self):
        config = financial_transaction_preset(
            bq_project="proj",
            source_table="proj.ds.tbl",
            columns={
                "first_name": "first_name",
                "account_number": "account_number",
            },
        )
        assert config.sources[0].entity_type == "FinancialAccount"

    def test_healthcare_preset_sets_entity_type(self):
        config = healthcare_patient_preset(
            bq_project="proj",
            source_table="proj.ds.tbl",
            columns={
                "first_name": "first_name",
                "mrn": "mrn",
            },
        )
        assert config.sources[0].entity_type == "Patient"

    def test_presets_generate_valid_configs(self):
        """All presets still generate valid PipelineConfigs."""
        for preset_fn, cols in [
            (person_dedup_preset, {"fn": "first_name", "ln": "last_name"}),
            (business_dedup_preset, {"cn": "company_name", "ein": "ein"}),
            (insurance_dedup_preset, {"fn": "first_name", "pn": "policy_number"}),
            (healthcare_patient_preset, {"fn": "first_name", "mrn": "mrn"}),
        ]:
            config = preset_fn(
                bq_project="proj",
                source_table="proj.ds.tbl",
                columns=cols,
            )
            assert len(config.matching_tiers) >= 1
            assert len(config.sources) == 1
