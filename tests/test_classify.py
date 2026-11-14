import pytest

from mining_alerts.classify import categorize
from mining_alerts.models import Announcement


def cats(title, summary=""):
    return categorize(Announcement(title=title, url="u", source="t", summary=summary))


@pytest.mark.parametrize("title, first", [
    ("Elemental Royalty to Acquire Gold Stream Portfolio", "M&A"),
    ("OR Royalties Announces Acquisition of a Precious Metals Stream", "M&A"),
    ("Altius Minerals acquires new copper royalty", "M&A"),
    ("Cornish Metals Closes US$210M Bond Financing", "Financing"),
    ("Argentina Potash secures DFC funding for El Ceibo", "Financing"),
    ("Heliostar Files Updated Mineral Resource Estimate for Ana Paula", "Resource/Study"),
    ("Heliostar Submits Environmental Permit Applications for Ana Paula", "Permits"),
    ("Proyecto adhiere al RIGI en Neuquén", "Permits"),
    ("Court rules in LRC's favour in Thacker Pass royalty litigation", "Royalty/Stream"),
    ("Heliostar Drills 101 Metres Grading 5.34 g/t Gold", "Drilling"),
    ("Lithium Americas begins construction at Thacker Pass", "Production"),
    ("Gold.com Reports Fiscal Q1 2027 Results", "Results"),
    ("Altius appoints new CFO", "Management"),
])
def test_first_category(title, first):
    assert cats(title)[0] == first


def test_multiple_tags_and_filing():
    c = cats("[SEC 8-K] Current report", "Lithium Americas announces financing and court ruling")
    assert c[0] == "Filing" and "Financing" in c and "Legal" in c


def test_uncategorized():
    assert cats("Heliostar to present at conference in Denver") == []
