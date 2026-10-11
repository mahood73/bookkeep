import asyncio
from unittest.mock import AsyncMock,patch
import pytest
from fastapi import HTTPException
from app.hardcover_matching import resolve_work, canonical_family, agrees_with_library


def test_canonical_chain_resolves_to_verified_work():
    async def gql(query, variables, db):
        return {'books_by_pk': {1:{'id':1,'canonical_id':2},2:{'id':2,'canonical_id':3},3:{'id':3,'canonical_id':None,'title':'Canonical'}}[variables['id']]}
    with patch('app.routers.hardcover.execute_graphql',side_effect=gql):
        assert asyncio.run(resolve_work(1,None))['id']==3

@pytest.mark.parametrize('records', [
    {1:{'id':1,'canonical_id':2},2:{'id':2,'canonical_id':1}},
    {1:None},
    {1:{'id':1,'canonical_id':None,'state':'deleted'}},
])
def test_invalid_canonical_chain_is_not_accepted(records):
    async def gql(query,variables,db):return {'books_by_pk':records[variables['id']]}
    with patch('app.routers.hardcover.execute_graphql',side_effect=gql),pytest.raises(HTTPException):
        asyncio.run(resolve_work(1,None))


def test_reverse_aliases_include_indirect_conflicts():
    async def gql(query,variables,db):
        return {'books': [{'id':2}] if variables['ids']==[1] else [{'id':3}] if variables['ids']==[2] else []}
    with patch('app.routers.hardcover.execute_graphql',side_effect=gql):
        assert asyncio.run(canonical_family(1,None))=={1,2,3}


def test_legitimate_collection_is_not_globally_rejected():
    assert agrees_with_library({'title':'Collected Stories','compilation':True,'contributions':[{'author':{'name':'A. Writer'}}]},'Collected Stories','A. Writer')
    assert not agrees_with_library({'title':'Collected Stories','compilation':False,'contributions':[{'author':{'name':'A. Writer'}}]},'A single story','A. Writer')
