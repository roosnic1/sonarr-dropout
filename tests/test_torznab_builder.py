"""Tests for TorznabBuilder XML generation."""

from datetime import datetime, timezone

from lxml import etree

from sonarr_dropout.torznab_builder import ReleaseItem, TorznabBuilder

NEWZNAB_NS = "http://www.newznab.com/DTD/2010/feeds/attributes/"

SAMPLE_ITEM = ReleaseItem(
    title="Game Changer S08E02 Rulette 2",
    guid="dropout-369988-8-2",
    link="http://localhost:8080/sabnzbd/nzb/369988/8/2",
    season=8,
    episode=2,
    tvdbid=369988,
)


def _parse_xml(text: str) -> etree._Element:
    return etree.fromstring(text.encode())


def _get_newznab_attr(item: etree._Element, name: str) -> str | None:
    for attr in item.findall(f"{{{NEWZNAB_NS}}}attr"):
        if attr.get("name") == name:
            return attr.get("value")
    return None


class TestBuildSearchResults:
    def test_item_has_expected_fields(self):
        xml = TorznabBuilder.build_search_results([SAMPLE_ITEM], "tvsearch")
        item = _parse_xml(xml).findall(".//item")[0]

        assert item.find("title").text == SAMPLE_ITEM.title
        assert item.find("link").text == SAMPLE_ITEM.link
        assert item.find("enclosure").get("url") == SAMPLE_ITEM.link
        assert item.find("enclosure").get("type") == "application/x-nzb"
        assert _get_newznab_attr(item, "season") == "8"
        assert _get_newznab_attr(item, "episode") == "2"
        assert _get_newznab_attr(item, "category") == str(TorznabBuilder.CATEGORY_TV_HD)
        assert _get_newznab_attr(item, "tvdbid") == "369988"

    def test_empty_items_produces_no_items(self):
        xml = TorznabBuilder.build_search_results([], "tvsearch")
        assert len(_parse_xml(xml).findall(".//item")) == 0

    def test_multiple_items(self):
        other = ReleaseItem(
            title="Dimension 20 S08E03", guid="g2", link="http://x/3", season=8, episode=3,
        )
        xml = TorznabBuilder.build_search_results([SAMPLE_ITEM, other], "tvsearch")
        assert len(_parse_xml(xml).findall(".//item")) == 2

    def test_uses_provided_pub_date(self):
        item = ReleaseItem(
            title="t", guid="g", link="l", season=1, episode=1,
            pub_date=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        )
        xml = TorznabBuilder.build_search_results([item], "tvsearch")
        pub_date = _parse_xml(xml).find(".//item/pubDate").text
        assert pub_date == "Fri, 02 Jan 2026 03:04:05 +0000"


class TestBuildCapabilities:
    def test_tv_only(self):
        root = _parse_xml(TorznabBuilder.build_capabilities())
        searching = root.find("searching")
        assert searching.find("tv-search") is not None
        assert searching.find("movie-search") is None

        categories = root.find("categories")
        assert categories.find("category").get("id") == str(TorznabBuilder.CATEGORY_TV)


class TestBuildError:
    def test_sets_code_and_description(self):
        root = _parse_xml(TorznabBuilder.build_error(100, "boom"))
        assert root.tag == "error"
        assert root.get("code") == "100"
        assert root.get("description") == "boom"
