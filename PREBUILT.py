from __future__ import annotations

import json
import os
from typing import List, Optional

from dotenv import load_dotenv
from langchain_core.tools import tool, BaseTool
from langchain_community.tools import TavilySearchResults
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain_groq import ChatGroq

try:
    from langchain_google_community import GmailToolkit
except ImportError:
    GmailToolkit = None

load_dotenv()


class PrebuiltTools:
    def __init__(
        self,
        faiss_path: str = "faiss_index",
        groq_model: str = "llama3-8b-8192",
        temperature: float = 0.5,
    ):
        self.faiss_path = faiss_path
        self.model = ChatGroq(model=groq_model, temperature=temperature)

        self.retriever = None
        if os.path.exists(self.faiss_path):
            vectorstore = FAISS.load_local(
                self.faiss_path,
                OpenAIEmbeddings(),
                allow_dangerous_deserialization=True,
            )
            self.retriever = vectorstore.as_retriever(search_kwargs={"k": 4})

    def websearch_tool(self) -> BaseTool:
        """Search the web using Tavily."""

        @tool
        def websearch(query: str) -> str:
            """Search the web for recent or factual information."""
            try:
                search_tool = TavilySearchResults(max_results=5)
                result = search_tool.invoke({"query": query})

                if isinstance(result, (dict, list)):
                    return json.dumps(result, indent=2, ensure_ascii=False)

                return str(result)
            except Exception as e:
                return f"Web search failed: {e}"

        return websearch

    def retrieve_data_tool(self) -> BaseTool:
        """Retrieve relevant chunks from FAISS."""

        @tool
        def retrieve_data(query: str) -> str:
            """Use this for asking questions over the vector database / RAG index."""
            try:
                if self.retriever is None:
                    return "Retriever is not initialized. FAISS index not found."

                docs = self.retriever.invoke(query)
                if not docs:
                    return "No relevant documents found."

                return "\n\n".join(doc.page_content for doc in docs[:4])
            except Exception as e:
                return f"Retrieval failed: {e}"

        return retrieve_data

    def get_sql_tools(self, db_uri: str) -> List[BaseTool]:
        """Return SQL toolkit tools for the given database URI."""
        db = SQLDatabase.from_uri(db_uri)
        toolkit = SQLDatabaseToolkit(db=db, llm=self.model)
        return toolkit.get_tools()

    def get_gmail_tools(self) -> List[BaseTool]:
        """Return Gmail tools from the Google community toolkit."""
        if GmailToolkit is None:
            return []

        credentials_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
        if not os.path.exists(credentials_file):
            return []

        try:
            toolkit = GmailToolkit()
            return toolkit.get_tools()
        except Exception:
            return []

    def custom_picture_tool(self) -> BaseTool:
        """Placeholder for your custom image/picture tool."""

        @tool
        def picture_tool(prompt: str) -> str:
            """Generate or edit an image from a text prompt."""
            return f"Picture tool called with prompt: {prompt}"

        return picture_tool

    def get_all_tools(self, db_uri: Optional[str] = None) -> List[BaseTool]:
        tools: List[BaseTool] = [
            self.websearch_tool(),
            self.retrieve_data_tool(),
            self.custom_picture_tool(),
        ]

        if db_uri:
            tools.extend(self.get_sql_tools(db_uri))

        tools.extend(self.get_gmail_tools())
        return tools