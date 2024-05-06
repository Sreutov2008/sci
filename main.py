from typing import List
from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from faststream.rabbit.fastapi import RabbitRouter, Logger
from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from jose import jwt
Base = declarative_base()


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)

    def __repr__(self):
        return f"<User(username='{self.username}')>"


engine = create_engine('postgresql://user:password@localhost/database')
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


SECRET_KEY = "your_secret_key"


def get_user(token: str, db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except jwt.JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return user


app = FastAPI()
router = RabbitRouter("amqp://guest:guest@localhost:5672/")


class MessageData(BaseModel):
    text: str
    room_id: str
    sender: str


class ConnectionManager:
    def __init__(self):
        self.connections: dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, room_id: str):
        await websocket.accept()
        if room_id not in self.connections:
            self.connections[room_id] = []
        if len(self.connections[room_id]) >= 2:
            await websocket.close(code=1008)  # Room is full
        else:
            self.connections[room_id].append(websocket)

    async def broadcast(self, room_id: str, message: str):
        if room_id in self.connections:
            living_connections = []
            for connection in self.connections[room_id]:
                try:
                    await connection.send_text(message)
                    living_connections.append(connection)
                except WebSocketDisconnect:
                    pass
            self.connections[room_id] = living_connections


manager = ConnectionManager()


@app.post("/message")
async def send_message(message: MessageData, logger: Logger = Depends(router.get_logger)):
    await manager.broadcast(message.room_id, message.text)
    await logger.publish_message(message.json(), routing_key=f"room.{message.room_id}")


@router.websocket("/updates/{room_id}")
async def get_updates(websocket: WebSocket, room_id: str, user: User = Depends(get_user)):
    await manager.connect(websocket, room_id)
    try:
        while True:
            message = await websocket.receive_text()
            # Handle incoming messages if needed
    except WebSocketDisconnect:
        pass
