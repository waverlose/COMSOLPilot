"""The recipe library must stay valid as the workflow schema evolves.

Every recipe is offered to the assistant as "known to work", so a spec that no
longer validates would be worse than no recipe at all.
"""

from src.tools.recipes import RECIPES, get_recipe, list_recipes
from src.tools.workflow import SpecValidator


class TestRecipesValidate:
    def test_every_recipe_passes_the_validator(self):
        for name, entry in RECIPES.items():
            result = SpecValidator(entry["spec"]).validate()
            assert result["errors"] == [], (name, result["errors"])

    def test_metadata_is_complete(self):
        for name, entry in RECIPES.items():
            for key in ("title", "physics", "notes", "check", "spec"):
                assert entry.get(key), (name, key)
            assert isinstance(entry["spec"], dict)

    def test_model_names_are_unique(self):
        names = [entry["spec"]["model"]["name"] for entry in RECIPES.values()]
        assert len(names) == len(set(names)), names


class TestRecipeTools:
    def test_listing_names_every_recipe(self):
        listing = list_recipes()
        assert listing["success"] is True
        assert listing["count"] == len(RECIPES)
        assert {item["name"] for item in listing["recipes"]} == set(RECIPES)

    def test_get_returns_a_runnable_spec(self):
        one = get_recipe("steady_heat_conduction")
        assert one["success"] is True
        assert one["spec"]["physics"][0]["type"] == "ht"
        assert one["how_to_run"]

    def test_unknown_recipe_is_reported(self):
        result = get_recipe("no_such_recipe")
        assert result["success"] is False
        assert "steady_heat_conduction" in result["available"]
