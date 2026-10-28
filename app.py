import os, sqlite3, secrets
from contextlib import contextmanager
from fastapi import FastAPI, Header, HTTPException, Depends, Query
from pydantic import BaseModel, Field, ConfigDict, field_validator
DB=os.getenv('DATABASE_PATH','inventory.db')
app=FastAPI(title='Stockroom Inventory API',version='1.0.0')
@contextmanager
def db():
    con=sqlite3.connect(DB,timeout=10);con.row_factory=sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.executescript('CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>=0), price_cents INTEGER NOT NULL CHECK(price_cents>=0)); CREATE TABLE IF NOT EXISTS movements(id INTEGER PRIMARY KEY, product_id INTEGER REFERENCES products(id), delta INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);')
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback();raise
    finally: con.close()
def authorize(x_api_key: str=Header(default='')):
    expected=os.getenv('INVENTORY_API_KEY','')
    if not expected: raise HTTPException(503,'Set INVENTORY_API_KEY before using write endpoints')
    if not secrets.compare_digest(x_api_key,expected):raise HTTPException(401,'Invalid API key')
class Product(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True,extra='forbid')
    sku:str=Field(min_length=1,max_length=40,pattern=r'^[A-Za-z0-9_-]+$')
    name:str=Field(min_length=1,max_length=100)
    quantity:int=Field(ge=0,strict=True)
    price_cents:int=Field(ge=0,strict=True)
class Movement(BaseModel):
    delta:int=Field(strict=True,ge=-1000000000,le=1000000000)
    @field_validator('delta')
    @classmethod
    def nonzero(cls,value):
        if value==0:raise ValueError('Movement must be nonzero')
        return value
@app.get('/health')
def health():
    with db() as con:con.execute('SELECT 1')
    return {'status':'ok'}
@app.get('/products')
def products(q:str=Query('',max_length=100),limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0)):
    with db() as con:
        rows=con.execute('SELECT * FROM products WHERE instr(lower(name),lower(?))>0 ORDER BY id LIMIT ? OFFSET ?',(q,limit,offset)).fetchall()
        total=con.execute('SELECT COUNT(*) FROM products WHERE instr(lower(name),lower(?))>0',(q,)).fetchone()[0]
    return {'items':[dict(x) for x in rows],'total':total,'limit':limit,'offset':offset}
@app.post('/products',status_code=201,dependencies=[Depends(authorize)])
def create(p:Product):
    with db() as con:
        try:
            cur=con.execute('INSERT INTO products(sku,name,quantity,price_cents) VALUES(?,?,?,?)',(p.sku,p.name,p.quantity,p.price_cents))
        except sqlite3.IntegrityError:raise HTTPException(409,'SKU already exists')
        return {'id':cur.lastrowid,**p.model_dump()}
@app.get('/products/{product_id}')
def get(product_id:int):
    with db() as con:row=con.execute('SELECT * FROM products WHERE id=?',(product_id,)).fetchone()
    if not row:raise HTTPException(404,'Product not found')
    return dict(row)
@app.post('/products/{product_id}/movements',dependencies=[Depends(authorize)])
def move(product_id:int,m:Movement):
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT quantity FROM products WHERE id=?',(product_id,)).fetchone()
        if not row:raise HTTPException(404,'Product not found')
        if row[0]+m.delta<0:raise HTTPException(409,'Insufficient stock')
        con.execute('UPDATE products SET quantity=quantity+? WHERE id=?',(m.delta,product_id))
        con.execute('INSERT INTO movements(product_id,delta) VALUES(?,?)',(product_id,m.delta))
        return dict(con.execute('SELECT * FROM products WHERE id=?',(product_id,)).fetchone())
@app.get('/movements')
def history(limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0)):
    with db() as con:return {'items':[dict(x) for x in con.execute('SELECT * FROM movements ORDER BY id DESC LIMIT ? OFFSET ?',(limit,offset))]}
@app.get('/summary')
def summary():
    with db() as con:
        row=con.execute('SELECT COUNT(*) products,COALESCE(SUM(quantity),0) units,COALESCE(SUM(quantity*price_cents),0) value_cents FROM products').fetchone()
    return dict(row)
