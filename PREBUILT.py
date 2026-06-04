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
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.chains import RetrievalQA
from langchain_core.retrievers import VectorStoreRetriever
from langchain_core.vectorstores import FAISS
from langchain_core.embeddings import OpenAIEmbeddings  
from langchain_core.prompts import PromptTemplate
from langchain_core.chains import LLMChain
from langchain_core import LLM
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.chains import SequentialChain
from langchain_core.chains import SimpleSequentialChain
from langchain_google_community import GmailToolkit, GmailSearchTool, GmailReadTool, GmailSendTool
from langchain_core.tools import BaseTool



class prebuilt:
    def __init__(self):
        self.retriever = VectorStoreRetriever(vectorstore=FAISS.load_local("faiss_index", OpenAIEmbeddings()))
        self.model = ChatGroq(model="llama3-8b-8192", temperature=0.5)
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
    def retrieve_data(query:str) -> str:
        """Given a query, this tool retrieves relevant information from a vector store and provides an answer based on the retrieved data.
        """
        docs = self.retriever.invoke(query)
        return "\n\n".join(d.page_content for d in docs[:4])
    def gmail_search(self,query:str) -> str:
        """Given a query, this tool searches the user's Gmail inbox for relevant emails and returns a summary of the search results."""
        search_tool = self.GmailSearchTool()
        return search_tool.invoke(query)
    def gmail_read(self,email_id:str) -> str:
        """Given an email ID, this tool retrieves the content of the specified email from the user's Gmail inbox and returns it as a string."""
        read_tool = self.GmailReadTool()
        return read_tool.invoke(email_id)
    def gmail_send(self,reciption:str,subject:str,body:str) -> str:
        """Given the recipient's email address, subject, and body of the email, this tool sends an email using the user's Gmail account and returns a confirmation message."""
        send_tool = self.GmailSendTool()
        return send_tool.invoke(reciption,subject,body)
    
