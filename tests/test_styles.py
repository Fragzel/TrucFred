import pytest

from newrel.styles import normalize, pick, split_tags, style_of, useful


@pytest.mark.parametrize(
    ("label", "style"),
    [
        # Rap, y compris quand un autre genre est cité
        ("Hip-hop & Rap", "rap"),
        ("rap francais", "rap"),
        ("hardcore hip hop", "rap"),
        ("instru rap", "rap"),
        # L'électro en sous-styles
        ("Hardcore", "hardcore"),
        ("Gabber", "hardcore"),
        ("frenchcore", "hardcore"),
        ("Drum & Bass", "dnb"),
        ("drum'n'bass", "dnb"),
        ("Drum-n-Bass", "dnb"),
        ("jump up", "dnb"),
        ("liquid funk", "dnb"),
        ("Techno", "techno"),
        ("acid techno", "techno"),
        ("tekno", "techno"),
        ("dub techno", "techno"),
        ("Deep House", "house"),
        ("acid house", "house"),
        ("Dubstep", "bass"),
        ("psytrance", "trance"),
        ("Hardstyle", "hardstyle"),
        ("Electronic music", "electro"),
        ("Dance & EDM", "electro"),
        # Les mêmes mots dans d'autres familles
        ("hardcore punk", "rock"),
        ("pop rock", "rock"),
        ("acid jazz", "jazz"),
        ("Dub", "reggae"),
        ("funk carioca", "world"),
        ("Reggaeton", "world"),
        ("R&B & Soul", "rnb"),
        ("Rhythm_and_blues", "rnb"),
        ("Pop music", "pop"),
        ("synthpop", "pop"),
        ("Folk & Singer-Songwriter", "folk"),
        ("Soundtrack", "classical"),
        # Rien d'exploitable
        ("Music", None),
        ("Independent music", None),
        ("indie", None),
        ("lollipop", None),
        ("jump up ain't my fault", None),  # une phrase, pas un genre
        ("", None),
    ],
)
def test_style_d_un_genre(label, style) -> None:
    assert style_of(label) == style


def test_normalisation_des_genres() -> None:
    assert normalize("Drum-n-Bass") == normalize("drum & bass") == "drum and bass"
    assert normalize("Électro_Swing") == "electro swing"


def test_tags_entre_guillemets() -> None:
    assert split_tags('techno "acid techno" rave') == ["techno", "acid techno", "rave"]
    assert split_tags('techno "acid') == ["techno", "acid"]  # guillemet orphelin
    assert split_tags(None) == []


def test_genres_utiles_sans_doublon() -> None:
    labels = ["Music", "Techno", "techno", "indie", "Hip hop"]
    assert useful(labels) == ["Techno", "Hip hop"]


def test_tags_hors_de_la_famille_des_sujets_ignores() -> None:
    labels = ["Electronic music", "gabber", "r&b", "acid"]
    assert useful(labels, within=["Electronic music", "Music"]) == [
        "Electronic music",
        "gabber",
        "acid",
    ]
    assert useful(["r&b"], within=["Music"]) == ["r&b"]  # sans sujet reconnu, rien n'est filtré


def test_electro_precisee_par_un_sous_style() -> None:
    styles, genres = pick([["Electronic music"], [], ["Gabber", "Hardcore"]])
    assert styles == ["hardcore"]
    assert genres == ["Gabber", "Hardcore"]


def test_genres_de_la_sortie_avant_ceux_de_l_artiste() -> None:
    assert pick([["Techno"], ["rap francais"], []])[0] == ["techno", "rap"]
    assert pick([["Techno"], [], ["rap francais"]])[0] == ["techno"]  # trop léger : ignoré


def test_deuxieme_style_seulement_s_il_pese_assez() -> None:
    assert pick([["Techno", "acid", "tekno", "Hip hop"]])[0] == ["techno"]
    assert pick([["Techno", "Hip hop"]])[0] == ["techno", "rap"]
    assert pick([["Rock", "Pop", "Jazz"]])[0] == ["rock", "pop"]


def test_a_egalite_l_ordre_des_genres_decide() -> None:
    assert pick([["Hip hop music", "Electronic music"]])[0] == ["rap", "electro"]
    assert pick([["Electronic music", "Hip hop music"]])[0] == ["electro", "rap"]


def test_sans_genre_reconnu_aucun_style() -> None:
    assert pick([["Music"], [], []]) == ([], [])
    assert pick([]) == ([], [])


def test_genres_affiches_limites() -> None:
    labels = ["Techno", "acid", "tekno", "hardtek", "schranz", "minimal"]
    assert pick([labels])[1] == ["Techno", "acid", "tekno", "hardtek"]
