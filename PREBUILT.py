from pydantic import BaseModel,Field
from fastapi import FastAPI
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.tools import TavilySearchResults
from langchain_core.tools import tool, BaseTool
from langchain_core.messages import HumanMessage
from langchain_core.tools import InjectedToolArg
from langchain_protocol import Annotated
from dotenv import load_dotenv
import os
from langchain_groq import ChatGroq, GroqClient

class prebuilt:
    def init__(self):
        model = model = ChatGroq(model="llama3-8b-8192", temperature=0.5)
    def websearch(self,query):
        if self.TavilySearchResults is None:
            raise ImportError("TavilySearchResults tool is not available. Please install langchain_community to use this feature.")
        search_tool = self.TavilySearchResults()
        return search_tool.invoke(query)
    
    def get_sql_toolkit(self,db_uri:str) -> str:
        """Given a path to a SQL database file,this tool is used to give response based on this database file """
        db = self.SQLDatabase.from_uri(db_uri)
        toolkit = self.SQLDatabaseToolkit(db=db,model=self.model)
        return toolkit.get_tools()
    
    