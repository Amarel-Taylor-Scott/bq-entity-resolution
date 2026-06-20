"""Tests for stages barrel exports (all stage classes importable)."""

import bq_entity_resolution.stages as stages_module

# The expected stage class names that should be in __all__
EXPECTED_STAGES = [
    "Stage",
    "TableRef",
    "StageResult",
    "StagingStage",
    "FeatureEngineeringStage",
    "TermFrequencyStage",
    "BlockingStage",
    "MatchingStage",
    "MatchAccumulationStage",
    "ClusteringStage",
    "CanonicalIndexInitStage",
    "CanonicalIndexPopulateStage",
    "GoldOutputStage",
    "ClusterQualityStage",
    "ActiveLearningStage",
    "LabelIngestionStage",
    "FeatureMatrixExportStage",
    "BQMLTrainingStage",
    "BQMLPredictStage",
    "BQMLEvaluateStage",
    "PlaceholderDetectionStage",
]


class TestBarrelExports:
    """Test that all stage classes are importable from bq_entity_resolution.stages."""

    def test_all_expected_stages_importable(self):
        """Every expected stage class is accessible as an attribute."""
        for name in EXPECTED_STAGES:
            assert hasattr(stages_module, name), (
                f"Stage '{name}' is not importable from bq_entity_resolution.stages"
            )

    def test_all_expected_stages_in_all(self):
        """__all__ includes all expected stage class names."""
        all_names = set(stages_module.__all__)
        for name in EXPECTED_STAGES:
            assert name in all_names, (
                f"Stage '{name}' is missing from stages.__all__"
            )

    def test_no_extra_unexpected_exports(self):
        """__all__ only contains expected exports (no typos or removed items)."""
        all_names = set(stages_module.__all__)
        expected_set = set(EXPECTED_STAGES)
        extra = all_names - expected_set
        assert not extra, f"Unexpected exports in stages.__all__: {extra}"


class TestStageClassesAreClasses:
    """Test that exported stage names are actual classes (not None or strings)."""

    def test_stage_base_is_class(self):
        """Stage is a class."""
        assert isinstance(stages_module.Stage, type)

    def test_table_ref_is_class(self):
        """TableRef is a class."""
        assert isinstance(stages_module.TableRef, type)

    def test_staging_stage_is_class(self):
        """StagingStage is a class."""
        assert isinstance(stages_module.StagingStage, type)

    def test_feature_engineering_stage_is_class(self):
        """FeatureEngineeringStage is a class."""
        assert isinstance(stages_module.FeatureEngineeringStage, type)

    def test_blocking_stage_is_class(self):
        """BlockingStage is a class."""
        assert isinstance(stages_module.BlockingStage, type)

    def test_matching_stage_is_class(self):
        """MatchingStage is a class."""
        assert isinstance(stages_module.MatchingStage, type)

    def test_match_accumulation_stage_is_class(self):
        """MatchAccumulationStage is a class."""
        assert isinstance(stages_module.MatchAccumulationStage, type)

    def test_clustering_stage_is_class(self):
        """ClusteringStage is a class."""
        assert isinstance(stages_module.ClusteringStage, type)

    def test_canonical_index_init_stage_is_class(self):
        """CanonicalIndexInitStage is a class."""
        assert isinstance(stages_module.CanonicalIndexInitStage, type)

    def test_canonical_index_populate_stage_is_class(self):
        """CanonicalIndexPopulateStage is a class."""
        assert isinstance(stages_module.CanonicalIndexPopulateStage, type)

    def test_gold_output_stage_is_class(self):
        """GoldOutputStage is a class."""
        assert isinstance(stages_module.GoldOutputStage, type)

    def test_cluster_quality_stage_is_class(self):
        """ClusterQualityStage is a class."""
        assert isinstance(stages_module.ClusterQualityStage, type)

    def test_active_learning_stage_is_class(self):
        """ActiveLearningStage is a class."""
        assert isinstance(stages_module.ActiveLearningStage, type)

    def test_label_ingestion_stage_is_class(self):
        """LabelIngestionStage is a class."""
        assert isinstance(stages_module.LabelIngestionStage, type)

    def test_bqml_training_stage_is_class(self):
        """BQMLTrainingStage is a class."""
        assert isinstance(stages_module.BQMLTrainingStage, type)

    def test_bqml_predict_stage_is_class(self):
        """BQMLPredictStage is a class."""
        assert isinstance(stages_module.BQMLPredictStage, type)

    def test_bqml_evaluate_stage_is_class(self):
        """BQMLEvaluateStage is a class."""
        assert isinstance(stages_module.BQMLEvaluateStage, type)

    def test_feature_matrix_export_stage_is_class(self):
        """FeatureMatrixExportStage is a class."""
        assert isinstance(stages_module.FeatureMatrixExportStage, type)

    def test_term_frequency_stage_is_class(self):
        """TermFrequencyStage is a class."""
        assert isinstance(stages_module.TermFrequencyStage, type)

    def test_stage_result_is_class(self):
        """StageResult is a class."""
        assert isinstance(stages_module.StageResult, type)


class TestStageInheritance:
    """Test that concrete stage classes inherit from Stage."""

    def test_staging_inherits_from_stage(self):
        """StagingStage inherits from Stage."""
        assert issubclass(stages_module.StagingStage, stages_module.Stage)

    def test_feature_engineering_inherits_from_stage(self):
        """FeatureEngineeringStage inherits from Stage."""
        assert issubclass(stages_module.FeatureEngineeringStage, stages_module.Stage)

    def test_blocking_inherits_from_stage(self):
        """BlockingStage inherits from Stage."""
        assert issubclass(stages_module.BlockingStage, stages_module.Stage)

    def test_matching_inherits_from_stage(self):
        """MatchingStage inherits from Stage."""
        assert issubclass(stages_module.MatchingStage, stages_module.Stage)

    def test_clustering_inherits_from_stage(self):
        """ClusteringStage inherits from Stage."""
        assert issubclass(stages_module.ClusteringStage, stages_module.Stage)

    def test_gold_output_inherits_from_stage(self):
        """GoldOutputStage inherits from Stage."""
        assert issubclass(stages_module.GoldOutputStage, stages_module.Stage)

    def test_bqml_training_inherits_from_stage(self):
        """BQMLTrainingStage inherits from Stage."""
        assert issubclass(stages_module.BQMLTrainingStage, stages_module.Stage)
