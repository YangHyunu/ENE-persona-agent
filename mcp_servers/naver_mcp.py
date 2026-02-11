import os
import re
from typing import Annotated, Literal
import httpx
from dotenv import load_dotenv
from pydantic import Field
from fastmcp import FastMCP

# 환경 변수 로드
load_dotenv()
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

# MCP 서버 초기화
mcp = FastMCP("Naver MCP Server")


@mcp.tool(
        name="web_search",
        description="네이버 검색을 수행합니다."
)
async def web_search(
    query: Annotated[str, Field(description="검색어입니다. 시점이나 조건 등을 구체적으로 작성하세요.")],
    display: Annotated[int, Field(description="웹 문서를 최대 몇 건까지 검색할지 결정합니다.(1-100)", ge=1, le=100)] = 20,
    start: Annotated[int, Field(description="검색 시작 위치입니다.(1-1000)", ge=1, le=1000)] = 1,
    sort: Annotated[Literal["sim", "date"], Field(description="정렬 옵션입니다. sim=유사도순, date=최신순")] = "sim"
) -> dict:

    """
    네이버 검색 API를 호출해 결과를 구조화하여 반환합니다.

    Args:
        query: 검색어
        display: 검색 결과 수(1~100)
        start: 검색 시작 위치(1~1000)
        sort: 'sim' | 'date'

    Returns:
        {
          "query": str,
          "total": int,
          "items": [{"title": str, "link": str, "description": str}]}
        }
    """
    url = "https://openapi.naver.com/v1/search/webkr.json"
    params = {"query": query, "display": display, "start": start, "sort": sort}
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }

    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=headers, params=params)
        r.raise_for_status()
        data = r.json()

    results = []
    for item in data.get("items", []):
        results.append({
            "title": re.sub(r"<.*?>", "", item.get("title") or "").strip(),
            "link": item.get("link"),
            "description": re.sub(r"<.*?>", "", item.get("description") or "").strip(),
        })

    return {
        "query": query,
        "total": data.get("total", 0),
        "items": results,
    }


@mcp.tool(
    name="naver_blog_search",
    description="네이버 블로그 검색을 수행합니다."
)
async def naver_blog_search(
    query: Annotated[str, Field(description="검색어입니다. 시점이나 조건 등을 구체적으로 작성하세요.")],
    total: Annotated[int, Field(description="총 검색 결과 개수를 결정합니다.(1-100)", ge=1, le=100)] = 20,
    start: Annotated[int, Field(description="검색 시작 위치입니다.(1-1000)", ge=1, le=1000)] = 1,
    display: Annotated[int, Field(description="한 번에 표시할 검색 결과 개수.(1-100)", ge=1, le=100)] = 20,
    sort: Annotated[Literal["sim", "date"], Field(description="정렬 옵션입니다. sim=유사도순, date=최신순")] = "sim"
) -> dict:

    """
    네이버 블로그 API를 호출해 결과를 구조화하여 반환합니다.

    Args:
        query: 검색어
        display: 검색 결과 수(1~100)
        start: 검색 시작 위치(1~1000)
        sort: 'sim' | 'date'

    Returns:
        {
          "query": str,
          "total": int,
          "items": [{"title": str, "link": str, "description": str}]}
        }
    """
    url = "https://openapi.naver.com/v1/search/blog.json"
    params = {"query": query, "display": display, "start": start, "sort": sort}
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }

    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=headers, params=params)
        r.raise_for_status()
        data = r.json()

    results = []
    for item in data.get("items", []):
        results.append({
            "title": re.sub(r"<.*?>", "", item.get("title") or "").strip(),
            "link": item.get("link"),
            "description": re.sub(r"<.*?>", "", item.get("description") or "").strip(),
        })

    return {
        "query": query,
        "total": data.get("total", 0),
        "items": results,
    }


@mcp.tool(
    name="naver_shopping_search",
    description="네이버 쇼핑 검색을 수행합니다."
)
async def naver_shopping_search(
    query: Annotated[str, Field(description="검색어입니다. 시점이나 조건 등을 구체적으로 작성하세요.")],
    total: Annotated[int, Field(description="총 검색 결과 개수를 결정합니다.(1-100)", ge=1, le=100)] = 20,
    start: Annotated[int, Field(description="검색 시작 위치입니다.(1-1000)", ge=1, le=1000)] = 1,
    display: Annotated[int, Field(description="한 번에 표시할 검색 결과 개수.(1-100)", ge=1, le=100)] = 20,
    sort: Annotated[Literal["sim", "date"], Field(description="정렬 옵션입니다. sim=유사도순, date=최신순")] = "sim"
) -> dict:

    """
    네이버 쇼핑 API를 호출해 결과를 구조화하여 반환합니다.

    Args:
        query: 검색어
        display: 검색 결과 수(1~100)
        start: 검색 시작 위치(1~1000)
        sort: 'sim' | 'date'

    Returns:
        {
          "query": str,
          "total": int,
          "items": [{"title": str, "link": str, "description": str}]}
        }
    """
    url = "https://openapi.naver.com/v1/search/shop.json"
    params = {"query": query, "display": display, "start": start, "sort": sort}
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }

    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=headers, params=params)
        r.raise_for_status()
        data = r.json()

    results = []
    for item in data.get("items", []):
        results.append({
            "title": re.sub(r"<.*?>", "", item.get("title") or "").strip(),
            "link": item.get("link"),
            "description": re.sub(r"<.*?>", "", item.get("description") or "").strip(),
        })

    return {
        "query": query,
        "total": data.get("total", 0),
        "items": results,
    }
@mcp.tool(
    name="naver_place_search",
    description="네이버 플레이스 검색을 수행합니다."
)
async def naver_place_search(
    query: Annotated[str, Field(description="검색어입니다. 시점이나 조건 등을 구체적으로 작성하세요.")],
    total: Annotated[int, Field(description="총 검색 결과 개수를 결정합니다.(1-100)", ge=1, le=100)] = 20,
    start: Annotated[int, Field(description="검색 시작 위치입니다.(1-1000)", ge=1, le=1000)] = 1,
    display: Annotated[int, Field(description="한 번에 표시할 검색 결과 개수.(1-100)", ge=1, le=100)] = 20,
    sort: Annotated[Literal["sim", "date"], Field(description="정렬 옵션입니다. sim=유사도순, date=최신순")] = "sim"
) -> dict:

    """
    네이버 쇼핑 API를 호출해 결과를 구조화하여 반환합니다.

    Args:
        query: 검색어
        display: 검색 결과 수(1~100)
        start: 검색 시작 위치(1~1000)
        sort: 'sim' | 'date'

    Returns:
        {
          "query": str,
          "total": int,
          "items": [{"title": str, "link": str, "description": str}]}
        }
    """
    url = "https://openapi.naver.com/v1/search/local.json"
    params = {"query": query, "display": display, "start": start, "sort": sort}
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }

    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=headers, params=params)
        r.raise_for_status()
        data = r.json()

    results = []
    for item in data.get("items", []):
        results.append({
            "title": re.sub(r"<.*?>", "", item.get("title") or "").strip(),
            "link": item.get("link"),
            "description": re.sub(r"<.*?>", "", item.get("description") or "").strip(),
        })

    return {
        "query": query,
        "total": data.get("total", 0),
        "items": results,
    }

# 실행
if __name__ == "__main__":
    """
    FastMCP 서버를 streamable-http로 실행합니다.
    접속 URL은 http://127.0.0.1:8000/mcp/ 입니다.
    통신 방식을 변경하려면 `mcp.run()`의 `transport` 인자를 다음과 같이 수정하세요.
        - mcp.run(transport="stdio")
        - mcp.run(transport="sse")
    """
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8000, path="/mcp/")

