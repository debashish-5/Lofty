class prebuilt:
    try:
        from pydantic import BaseModel,Field
        from fastapi import FastAPI
        from langchain_community.utilities import SQLDatabase
        from langchain_community.agent_toolkits import SQLDatabaseToolkit
        from langchain_community.tools import TavilySearchResults
        from langchain_core.tools import tool, BaseTool
        from langchain_core.messages import HumanMessage
    except ImportError:
        TavilySearchResults = None
        SQLDatabase = None
        SQLDatabaseToolkit = None
    def websearch(self,query):
        if self.TavilySearchResults is None:
            raise ImportError("TavilySearchResults tool is not available. Please install langchain_community to use this feature.")
        search_tool = self.TavilySearchResults()
        return search_tool.run(query)
    @tool
    def sql_database_tool(self,databasefile:str) -> str:
        """Given a path to a SQL database file,this tool is used to give response based on this database file """
        DB_URI = f"mysql+pymysql://user:password@localhost:3306/{databasefile}"
        db = self.SQLDatabase.from_uri(DB_URI)
        