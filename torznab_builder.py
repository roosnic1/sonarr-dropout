import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from lxml import etree

logger = logging.getLogger(__name__)


def _to_xml(root: etree._Element) -> str:
    return etree.tostring(
        root, pretty_print=True, xml_declaration=True, encoding="UTF-8"
    ).decode("utf-8")


@dataclass
class ReleaseItem:
    """A single Torznab release -- one dropout.tv episode."""

    title: str
    guid: str
    link: str
    season: int
    episode: int
    size: int = 0
    pub_date: Optional[datetime] = None


class TorznabBuilder:
    """Build Torznab/Newznab compatible XML responses"""

    # dropout.tv is TV-only and consistently HD -- no movie/SD/UHD categories
    CATEGORY_TV = 5000
    CATEGORY_TV_HD = 5040

    @staticmethod
    def build_capabilities() -> str:
        """Build capabilities XML response"""
        root = etree.Element("caps")

        # Server info
        server = etree.SubElement(root, "server")
        server.set("version", "1.0")
        server.set("title", "sonarr-dropout")
        server.set("strapline", "dropout.tv Torznab Indexer")
        server.set("email", "")
        server.set("url", "https://www.dropout.tv")

        # Limits
        limits = etree.SubElement(root, "limits")
        limits.set("max", "100")
        limits.set("default", "100")

        # Registration
        registration = etree.SubElement(root, "registration")
        registration.set("available", "yes")
        registration.set("open", "yes")

        # Searching
        searching = etree.SubElement(root, "searching")
        search = etree.SubElement(searching, "search")
        search.set("available", "yes")
        search.set("supportedParams", "q")

        tv_search = etree.SubElement(searching, "tv-search")
        tv_search.set("available", "yes")
        tv_search.set("supportedParams", "q,tvdbid,season,ep")

        # Categories
        categories = etree.SubElement(root, "categories")

        cat_tv = etree.SubElement(categories, "category")
        cat_tv.set("id", str(TorznabBuilder.CATEGORY_TV))
        cat_tv.set("name", "TV")

        cat_tv_hd = etree.SubElement(cat_tv, "subcat")
        cat_tv_hd.set("id", str(TorznabBuilder.CATEGORY_TV_HD))
        cat_tv_hd.set("name", "TV/HD")

        return _to_xml(root)

    @staticmethod
    def build_search_results(items: List[ReleaseItem], query_type: str = "search") -> str:
        """Build search results RSS XML response"""
        nsmap = {
            'newznab': 'http://www.newznab.com/DTD/2010/feeds/attributes/',
            'torznab': 'http://torznab.com/schemas/2015/feed'
        }
        root = etree.Element("rss", version="2.0", nsmap=nsmap)

        channel = etree.SubElement(root, "channel")

        # Channel metadata
        etree.SubElement(channel, "title").text = "sonarr-dropout"
        etree.SubElement(channel, "description").text = "dropout.tv Torznab Feed"
        etree.SubElement(channel, "link").text = "https://www.dropout.tv"

        # Response metadata
        response = etree.SubElement(channel, "{http://www.newznab.com/DTD/2010/feeds/attributes/}response")
        response.set("offset", "0")
        response.set("total", str(len(items)))

        for item in items:
            elem = TorznabBuilder._build_item(item)
            if elem is not None:
                channel.append(elem)

        return _to_xml(root)

    @staticmethod
    def _build_item(item: ReleaseItem) -> Optional[etree.Element]:
        """Build individual item element"""
        try:
            elem = etree.Element("item")

            etree.SubElement(elem, "title").text = item.title

            guid_elem = etree.SubElement(elem, "guid")
            guid_elem.text = item.guid
            guid_elem.set("isPermaLink", "false")

            # Link points at our own SABnzbd-emulation addurl target, not
            # dropout.tv directly -- see main.py's search_dropout().
            etree.SubElement(elem, "link").text = item.link
            etree.SubElement(elem, "comments").text = item.link

            pub_date = item.pub_date or datetime.now(timezone.utc)
            fmt = "%a, %d %b %Y %H:%M:%S +0000"
            etree.SubElement(elem, "pubDate").text = pub_date.strftime(fmt)

            etree.SubElement(elem, "size").text = str(item.size)

            enclosure = etree.SubElement(elem, "enclosure")
            enclosure.set("url", item.link)
            enclosure.set("length", str(item.size))
            enclosure.set("type", "application/x-nzb")

            # Sonarr/Prowlarr add this indexer as a Newznab indexer (it emulates
            # SABnzbd and uses x-nzb enclosures, not a torrent client), and their
            # NewznabRssParser.GetCategory() only recognizes <newznab:attr> --
            # <torznab:attr> is invisible to it and categories parse as empty.
            newznab_ns = "{http://www.newznab.com/DTD/2010/feeds/attributes/}"

            attr = etree.SubElement(elem, f"{newznab_ns}attr")
            attr.set("name", "category")
            attr.set("value", str(TorznabBuilder.CATEGORY_TV_HD))

            attr = etree.SubElement(elem, f"{newznab_ns}attr")
            attr.set("name", "size")
            attr.set("value", str(item.size))

            attr = etree.SubElement(elem, f"{newznab_ns}attr")
            attr.set("name", "season")
            attr.set("value", str(item.season))

            attr = etree.SubElement(elem, f"{newznab_ns}attr")
            attr.set("name", "episode")
            attr.set("value", str(item.episode))

            return elem

        except Exception as e:
            # Log error and skip this item
            logger.warning(f"Error building item: {e}")
            return None

    @staticmethod
    def build_error(code: int, description: str) -> str:
        """Build error XML response"""
        root = etree.Element("error")
        root.set("code", str(code))
        root.set("description", description)

        return _to_xml(root)
