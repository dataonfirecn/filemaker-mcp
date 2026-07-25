import pytest

from app.services.filemaker_odata_client import (
    FileMakerODataClient,
    FileMakerODataError,
    odata_key_literal,
    parse_odata_metadata,
    row_key_value,
)


SAMPLE_METADATA = """<?xml version="1.0" encoding="UTF-8"?>
<edmx:Edmx xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx" Version="4.0">
  <edmx:DataServices>
    <Schema xmlns="http://docs.oasis-open.org/odata/ns/edm" Namespace="DMS">
      <EntityType Name="Parts">
        <Key><PropertyRef Name="ROWID" /></Key>
        <Property Name="ROWID" Type="Edm.Int64" Nullable="false" />
        <Property Name="part_number" Type="Edm.String" />
        <NavigationProperty Name="零件关联产品" Type="Collection(DMS.Products)" />
      </EntityType>
      <EntityType Name="Products">
        <Key><PropertyRef Name="ID" /></Key>
        <Property Name="ID" Type="Edm.String" Nullable="false" />
        <Property Name="product_sku" Type="Edm.String" />
        <NavigationProperty Name="产品BOM" Type="Collection(DMS.BOM)" />
      </EntityType>
      <EntityType Name="BOM">
        <Key><PropertyRef Name="ROWID" /></Key>
        <Property Name="ROWID" Type="Edm.Int64" Nullable="false" />
        <Property Name="part_number" Type="Edm.String" />
      </EntityType>
      <EntityContainer Name="DMS">
        <EntitySet Name="Parts" EntityType="DMS.Parts">
          <NavigationPropertyBinding Path="零件关联产品" Target="Products" />
        </EntitySet>
        <EntitySet Name="Products" EntityType="DMS.Products">
          <NavigationPropertyBinding Path="产品BOM" Target="BOM" />
        </EntitySet>
        <EntitySet Name="BOM" EntityType="DMS.BOM" />
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>
"""


class SettingsStub:
    filemaker_host = "https://filemaker.example.test"
    filemaker_database = "DMS DB"
    filemaker_username = "api_user"
    filemaker_password = "secret"
    filemaker_timeout_seconds = 30.0
    filemaker_ssl_verify = False
    filemaker_odata_enabled = True
    filemaker_odata_version = "v4"
    filemaker_odata_auth_mode = "basic"
    filemaker_odata_fmid_token = ""
    filemaker_odata_max_top = 10

    @property
    def filemaker_odata_configured(self) -> bool:
        return True


class DisabledSettingsStub(SettingsStub):
    filemaker_odata_enabled = False

    @property
    def filemaker_odata_configured(self) -> bool:
        return False


class FakeResponse:
    def __init__(
        self,
        payload=None,
        *,
        text: str = "",
        status_code: int = 200,
    ):
        self._payload = payload if payload is not None else {}
        self.text = text
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300
        self.content = (text or "{}").encode("utf-8")

    def json(self):
        return self._payload


class FakeHTTPClient:
    def __init__(self):
        self.requests = []

    async def request(self, method, url, **kwargs):
        self.requests.append({"method": method, "url": url, **kwargs})
        if url.endswith("/$metadata"):
            return FakeResponse(text=SAMPLE_METADATA)
        if url.endswith("/DMS%20DB/"):
            return FakeResponse(
                {
                    "value": [
                        {"name": "零件", "kind": "EntitySet", "url": "https://example/零件"},
                        {"name": "產品", "kind": "EntitySet", "url": "https://example/產品"},
                    ]
                }
            )
        return FakeResponse(
            {
                "@odata.count": 27,
                "value": [
                    {"ROWID": 1, "part_number": "AL-001"},
                    {"ROWID": 2, "part_number": "AL-002"},
                ],
            }
        )

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_odata_records_builds_query_options_and_caps_top() -> None:
    client = FileMakerODataClient(SettingsStub())
    real_client = client._client
    fake_http = FakeHTTPClient()
    client._client = fake_http
    await real_client.aclose()

    result = await client.records(
        "Parts",
        select=["ROWID", "part_number"],
        filter_expr="startswith(part_number,'AL')",
        expand=["零件关联产品"],
        top=50,
        skip=3,
    )

    request = fake_http.requests[0]
    assert request["url"].startswith("https://filemaker.example.test/fmi/odata/v4/DMS%20DB/Parts?")
    assert "$top=10" in request["url"]
    assert "$skip=3" in request["url"]
    assert "$select=ROWID,part_number" in request["url"]
    assert "$filter=startswith(part_number,'AL')" in request["url"]
    assert "$expand=%E9%9B%B6%E4%BB%B6%E5%85%B3%E8%81%94%E4%BA%A7%E5%93%81" in request["url"]
    assert result["foundCount"] == 27
    assert result["returnedCount"] == 2


@pytest.mark.asyncio
async def test_odata_related_records_builds_navigation_url() -> None:
    client = FileMakerODataClient(SettingsStub())
    real_client = client._client
    fake_http = FakeHTTPClient()
    client._client = fake_http
    await real_client.aclose()

    await client.related_records("Parts", "40616", "零件关联产品", top=5)

    request = fake_http.requests[0]
    assert "/Parts(40616)/%E9%9B%B6%E4%BB%B6%E5%85%B3%E8%81%94%E4%BA%A7%E5%93%81?" in request["url"]
    assert "$top=5" in request["url"]


@pytest.mark.asyncio
async def test_odata_tables_reads_service_document() -> None:
    client = FileMakerODataClient(SettingsStub())
    real_client = client._client
    fake_http = FakeHTTPClient()
    client._client = fake_http
    await real_client.aclose()

    tables = await client.tables()

    assert [table["name"] for table in tables] == ["零件", "產品"]
    assert fake_http.requests[0]["url"] == "https://filemaker.example.test/fmi/odata/v4/DMS%20DB/"


def test_odata_metadata_parser_extracts_navigation_bindings() -> None:
    schema = parse_odata_metadata(SAMPLE_METADATA)
    parts = schema.entity_for_set("Parts")

    assert parts is not None
    assert parts.keys == ["ROWID"]
    assert [field.name for field in parts.fields] == ["ROWID", "part_number"]
    assert parts.navigation[0].name == "零件关联产品"
    assert parts.navigation[0].target_entity == "Products"
    assert parts.navigation[0].target_set == "Products"
    assert schema.navigation_for("Products", "产品BOM").target_set == "BOM"


def test_odata_key_literal_quotes_strings_and_keeps_numbers() -> None:
    assert odata_key_literal("40616") == "40616"
    assert odata_key_literal("AL'001") == "'AL''001'"
    assert odata_key_literal("('se2018-00','S39416')") == "'se2018-00','S39416'"


def test_row_key_value_prefers_metadata_keys_then_rowid() -> None:
    assert row_key_value({"ID": "P-1", "ROWID": 7}, ["ID"]) == "P-1"
    assert row_key_value({"ROWID": 7}, ["ID"]) == 7
    assert (
        row_key_value(
            {"@id": "https://host/fmi/odata/v4/DMS/%E9%9B%B6%E4%BB%B6('se2018-00','S39416')"},
            [],
        )
        == "('se2018-00','S39416')"
    )


@pytest.mark.asyncio
async def test_odata_disabled_raises_clear_error() -> None:
    client = FileMakerODataClient(DisabledSettingsStub())
    try:
        with pytest.raises(FileMakerODataError, match="disabled"):
            await client.records("Parts")
    finally:
        await client.close()
