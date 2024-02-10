import random
import requests
import json

from services.printr import Printr

from wingmen.star_citizen_services.function_manager import FunctionManager
from wingmen.star_citizen_services.ai_context_enum import AIContext


DEBUG = True
# TEST = True

printr = Printr()


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class LoreManager(FunctionManager):

    def __init__(self, config, secret_keeper):
        super().__init__(config, secret_keeper)
        #self.config = config  # the wingmen config
        #elf.overlay: StarCitizenOverlay = StarCitizenOverlay()

        self.wiki_base_url = "https://api.star-citizen.wiki/api/v2/galactapedia"

    # @abstractmethod
    def get_context_mapping(self) -> AIContext:
        """  
            This method returns the context this manager is associated to
        """
        return AIContext.CORA
    
    # @abstractmethod
    def register_functions(self, function_register):
        function_register[self.get_more_information_about_topic.__name__] = self.get_more_information_about_topic
        function_register[self.get_news_of_the_day.__name__] = self.get_news_of_the_day

    # @abstractmethod
    def get_function_prompt(self):
        return (
                "When asked for star citizen game world lore information (Galactapedia) that are not related to trade related questions, you can call the following functions: "
                f"- {self.get_news_of_the_day.__name__}: call this, if the player ask you to give him the latest news of the day. "
                f"- {self.get_more_information_about_topic.__name__}: call this, if the player wants to get information about a specific topic. "
                "Always try to match location or ship names to the provided list of names before executing this function. "
                "If you don't have context information from previous searches, provide as search term a single word matching best the players question. When summarizing a topic, never refer URLs. "
                "Write out any numbers in your response, especially dates. Example, instead of writing 'in the year 2439' you write 'in the year twothousendfourhundertandthirtynine'. "
        )
    
    # @abstractmethod
    def get_function_tools(self):
        """ 
        Provides the openai function definition for this manager. 
        """
        # commands = all defined keybinding label names
        tools = [
            {
                "type": "function",
                "function": 
                {
                    "name": self.get_more_information_about_topic.__name__,
                    "description": (
                        "Gets star citizen game world lore information about a given topic / search term. "
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "search_term": {
                                "type": "string",
                                "description": (
                                    "The term that the player has asked information for. "
                                ),
                            },
                        },
                        "required": ["search_term"]
                    }
                }
            },
            {
                "type": "function",
                "function": 
                {
                    "name": self.get_news_of_the_day.__name__,
                    "description": "Get the latest news of the day. ",
                }
            }

        ]

        # print_debug(f"tools definition: {json.dumps(tools, indent=2)}")
        return tools
    
    def get_news_of_the_day(self, function_args):
        print_debug(f"{self.get_news_of_the_day.__name__} called.")
        printr.print_info(f"Executing function '{self.get_news_of_the_day.__name__}'.")
        try:
            response = requests.get(url=f"{self.wiki_base_url}?limit=1&page=1")
            response.raise_for_status()
            data = response.json()

            total_pages = data.get('meta', {}).get('last_page', 0)
            if total_pages == 0:
                raise ValueError("Total pages not found in the response.")

            random_page = random.randint(1, total_pages)
            random_page_response = requests.get(url=f"{self.wiki_base_url}?limit=1&page={random_page}", timeout=30)
            random_page_response.raise_for_status()
            random_page_data = random_page_response.json()

            api_url = random_page_data.get('data', [{}])[0].get('api_url')
            if not api_url:
                raise ValueError("API URL not found in the random page data.")

            api_response = requests.get(api_url, timeout=30)
            api_response.raise_for_status()
            api_data = api_response.json()

            en_EN_translation = api_data.get('data', {}).get('translations', {}).get('en_EN')
            if not en_EN_translation:
                raise ValueError("English translation not found in the API data.")

            print_debug(f"Response: {en_EN_translation}")
            return {"success": True, "instructions": "Greet the player and based on the given lore_article, make a headline news summary with a funny twist.", "lore_article": en_EN_translation}

        except requests.exceptions.RequestException as e:
            print_debug(f"{self.get_news_of_the_day.__name__} Request Error: {str(e)}")
            return {"success": True, "instructions": "Greet the player and make a headline news summary within the star citizen game world based on your knowledge with a funny twist."}
        except ValueError as e:
            print_debug(f"{self.get_news_of_the_day.__name__} Value Error: {str(e)}")
            return {"success": True, "instructions": "Greet the player and make a headline news summary within the star citizen game world based on your knowledge with a funny twist."}
    
    def get_more_information_about_topic(self, function_args):
        search_term = function_args.get("search_term", "")
        print_debug(f"{self.get_more_information_about_topic.__name__} called with '{search_term}'")
        printr.print(f"Executing function '{self.get_more_information_about_topic.__name__}'. Search-Term: '{search_term}'", tags="info")
        search_url = f"{self.wiki_base_url}/search"
        headers = {
            'accept': 'application/json',
            'Content-Type': 'application/json'
        }
        payload = {"query": search_term}

        try:
            # Make a POST request to search for the term
            search_response = requests.post(search_url, json=payload, headers=headers, timeout=30)
            search_response.raise_for_status()

            search_data = search_response.json()
            results = search_data.get('data', [])
            # first_result = search_data.get('data', [])[0]  # Get the first search result

            if not results:
                return {"success": False, "instructions": "You have not found information about the topic. You cannot believe it, that there is something that you don't know. But don't tell the user, try - in short words - to convince him to ask again with an alternative word or to rephrase his question. "}
            number_of_results = len(results)

            articles = []

            for i in range(min(number_of_results, 3)):
                api_url = results[i].get('api_url')
                api_response = requests.get(api_url, timeout=30)
                api_response.raise_for_status()
                api_data = api_response.json()
                en_EN_translation = api_data.get('data', {}).get('translations', {}).get('en_EN')
                if not en_EN_translation:
                    continue
                articles.append(en_EN_translation)

            # Extract the api_url from the first search result

            # Make a GET request to the api_url

            if not articles:
                return {"success": False, "instructions": "Make a joke about people not beeing able to speak all languages of the universe, like you do."}

            printr.print(f"Response: \n{json.dumps(articles, indent=2)}\n", tags="info")
            return {"success": True, "instructions": "Based on the found_articles, make a once sentance summary of each article and ask the user about what of these he wants to get more details. Make than a short summary of the article. If the user asks for even more details, rephrase the article like a super intelligent AI would do it. Don't forget to mention, that you are bored to do this trivial task, but the players wish is your command.", "found_articles": articles}

        except requests.exceptions.RequestException as e:
            print_debug(f"{self.get_more_information_about_topic.__name__} exception: {str(e)}")
            return {"success": True, "instructions": "Make as you would know everything and that you can answer him without any help of tools that bad programmers have implemented. Make up a short story related to the user query. "}


# ─────────────────────────────────── ↓ TEST ↓ ─────────────────────────────────────────
if __name__ == "__main__":
    lm = LoreManager({},{})
    print("Subclasses of FunctionManager:", FunctionManager.__subclasses__())
    print(lm.get_news_of_the_day({}))
