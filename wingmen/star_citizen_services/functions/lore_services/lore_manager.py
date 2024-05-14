import random
import requests
import json

from services.printr import Printr

from wingmen.star_citizen_services.function_manager import FunctionManager
from wingmen.star_citizen_services.ai_context_enum import AIContext
import re


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

        self.current_call_identifier = None

    # @abstractmethod
    def get_context_mapping(self) -> AIContext:
        """  
            This method returns the context this manager is associated to
        """
        return AIContext.CORA
    
    # @abstractmethod
    def register_functions(self, function_register):
        function_register[self.search_information_in_galactapedia.__name__] = self.search_information_in_galactapedia
        function_register[self.get_news_of_the_day.__name__] = self.get_news_of_the_day
        function_register[self.request_information_from_galactapedia_entry_url.__name__] = self.request_information_from_galactapedia_entry_url

    # @abstractmethod
    def get_function_prompt(self):
        return (
                "When asked for star citizen game world lore information (Galactapedia) that are not related to trade related questions, you can call the following functions: "
                f"- {self.get_news_of_the_day.__name__}: call this, if the player ask you to give him the latest news of the day. "
                f"- {self.search_information_in_galactapedia.__name__}: call this, if the player wants to get information about a specific topic. "
                f"- {self.request_information_from_galactapedia_entry_url.__name__}: call this, if the user wants to get information about a related article. "
                "In this case, you need to provide the call_identifier along with the galactapedia_entry_url. "
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
                    "name": self.search_information_in_galactapedia.__name__,
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
            },
            {
                "type": "function",
                "function": 
                {
                    "name": self.request_information_from_galactapedia_entry_url.__name__,
                    "description": (
                        "Makes a request to a given galactapedia entry url to get information about that topic. "
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "galactapedia_entry_url": {
                                "type": "string",
                                "description": (
                                    "The URL of the galactapedia entry to get information from. "
                                )
                            },
                            "call_identifier": {
                                "type": "integer",
                                "description": (
                                    "The call_identifier that was provided by the previous search_information_in_galactapedia function. "
                                )
                            },
                        },
                        "required": ["galactapedia_entry_url", "call_identifier"]
                    }
                }
            },

        ]

        # print_debug(f"tools definition: {json.dumps(tools, indent=2)}")
        return tools
    
    def cora_start_information(self):
        return "What are the news of the day? "
    
    def get_news_of_the_day(self, function_args):
        print_debug(f"{self.get_news_of_the_day.__name__} called.")
        printr.print(f"Executing function '{self.get_news_of_the_day.__name__}'.", tags="info")
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

            result = self.request_information_from_galactapedia_entry_url(
                    function_args={
                        "galactapedia_entry_url": api_url, 
                        "call_identifier": self.current_call_identifier
                    })
            
            if result.get("success", False) is False:
                return result
            
            result["additional_instructions"] = "Based on the given article, make a headline news summary. " + result["additional_instructions"]
            printr.print(f"News of the day: {json.dumps(result, indent=2)}", tags="info")
            return result

        except requests.exceptions.RequestException as e:
            print_debug(f"{self.get_news_of_the_day.__name__} Request Error: {str(e)}")
            printr.print(f"News of the day: Request Error: {str(e)}", tags="error")
            return {"success": False, "additional_instructions": "You currently have no access to the intergalactic news network. Create a short information about a random topic within the star citizen universe lore from your knowledge that might be interesting for the player. "}
        except ValueError as e:
            print_debug(f"{self.get_news_of_the_day.__name__} Value Error: {str(e)}")
            printr.print(f"News of the day: Request Error: {str(e)}", tags="error")
            return {"success": False, "additional_instructions": "You currently have no access to the intergalactic news network. Create a short information about a random topic within the star citizen universe lore from your knowledge that might be interesting for the player. "}
    
    def search_information_in_galactapedia(self, function_args):
        search_url = f"{self.wiki_base_url}/search"
        search_term = function_args.get("search_term", "")
        print_debug(f"{self.search_information_in_galactapedia.__name__} called with '{search_term}'")
        printr.print(f"Executing function '{self.search_information_in_galactapedia.__name__}' with search term '{search_term}'.", tags="info")
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

            # Example response
            #     "data": [
            #         {
            #         "id": "VY4Wnv7ZgW",
            #         "title": "Banu-Human First Contact",
            #         "slug": "banu-human-first-contact",
            #         "thumbnail": "https://cig-galactapedia-prod.s3.amazonaws.com/upload/f20bf4e3-15a5-41b5-ada8-2115a4997bec",
            #         "type": "Event",
            #         "rsi_url": "https://robertsspaceindustries.com/galactapedia/article/VY4Wnv7ZgW-banu-human-first-contact",
            #         "api_url": "https://api.star-citizen.wiki/api/v2/galactapedia/VY4Wnv7ZgW",
            #         "created_at": "2021-02-08T00:47:01.000000Z"
            #         },
            #         {
            #         "id": "RPPxJdLBJj",
            #         "title": "Banu Language",
            #         "slug": "banu-language",
            #         "thumbnail": "https://cig-galactapedia-prod.s3.amazonaws.com/upload/3c107dd7-4385-4a72-bf31-6d8881a0e7e4",
            #         "type": null,
            #         "rsi_url": "https://robertsspaceindustries.com/galactapedia/article/RPPxJdLBJj-banu-language",
            #         "api_url": "https://api.star-citizen.wiki/api/v2/galactapedia/RPPxJdLBJj",
            #         "created_at": "2021-02-08T00:48:42.000000Z"
            #         },

            results = search_data.get('data', [])
            if not results:
                printr.print(f"Search term '{search_term}' not found in the galactapedia. ", tags="info")
                return {"success": False, "additional_instructions": "You have not found information about the topic. Ask the user about a search term that is more specific. "}
            
            number_of_results = len(results)

            self.current_call_identifier = random.randint(0, 1000000)
            if number_of_results == 1:
                api_url = results[0].get('api_url')
                
                result = self.request_information_from_galactapedia_entry_url(
                    function_args={
                        "galactapedia_entry_url": api_url, 
                        "call_identifier": self.current_call_identifier
                    })
                printr.print(f"Found a single article about the topic. {json.dumps(result, indent=2)}", tags="info")
                return result

            articles = []

            for i in range(min(number_of_results, 10)):
                result = results[i]
                title = result.get('title')
                api_url = result.get('api_url')
                article_type = result.get('type')
                articles.append({"title": title, "type": article_type, "galactapedia_entry_url": api_url})

            result = {"success": True, 
                    "additional_instructions": (
                        "You have found several articles about the topic. "
                        "Provide the title of the articles to the user and ask him, "
                        "if he wants to get more information about one or more of these. "
                        "If he is interested in one of the articles, "
                        "request more information with the provided galactapedia_entry_url. "
                        "For subsequent requests, you have to provide the call_identifier. "), 
                    "found_articles": articles, 
                    "call_identifier": self.current_call_identifier}
            printr.print(f"Found several articles about the topic. {json.dumps(result, indent=2)}", tags="info")
            return result
            
        except requests.exceptions.RequestException as e:
            if isinstance(e, requests.exceptions.HTTPError) and e.response.status_code == 404:
                printr.print("No entry found for the search term '{search_term}'. "
                             "Please check the spelling or suggest a correction.", tags="info")
                return {
                    "success": False,
                    "additional_instructions": f"No entry found for the search term '{search_term}'. "
                                               "Tell the player, you couldn't find information about the topic. Make a suggestion to correct the search term or ask him, to rephrase his question.",
                    "error": str(e)
                }
            else:
                print_debug(f"{self.search_information_in_galactapedia.__name__} exception: {str(e)}")
                printr.print(f"Error during search of '{search_term}' in the galactapedia: {str(e)} ", tags="info")
                return {
                    "success": False,
                    "additional_instructions": "Galactapedia is currently unavailable. Please try again later.",
                    "error": str(e)
                }
    
    def request_information_from_galactapedia_entry_url(self, function_args):
        api_url = function_args.get("galactapedia_entry_url", "")
        call_identifier = function_args.get("call_identifier", None)
        printr.print(f"Executing function '{self.request_information_from_galactapedia_entry_url.__name__}'. URL: {api_url}. ", tags="info")
        if self.current_call_identifier != call_identifier:
            return {"success": False, "additional_instructions": (
                "You are not allowed to make requests without a valid call_identifier. "
                "Ask the user about what topic he wants to retrieve information and call the appropriate function. ")
            }
        
        # Validate the API URL
        if not re.match(r'^https:\/\/api\.star-citizen\.wiki\/api\/v2\/galactapedia\/', api_url[:api_url.find("/galactapedia/") + len("/galactapedia/")]):
            printr.print(f"Unallowed URL: {api_url}. ", tags="error")
            return {"success": False, "additional_instructions": "You are not allowed to request information from this URL. "}
        
        print_debug(f"{self.request_information_from_galactapedia_entry_url.__name__} called with API URL: {api_url}. ")
        
        headers = {
            'accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        try:
            # Make a GET request to the API URL
            api_response = requests.get(api_url, headers=headers, timeout=30)
            api_response.raise_for_status()
            
            api_data = api_response.json()

        #     Example response
        #     {
        #     "data": {
        #         "id": "VY4Wnv7ZgW",
        #         "title": "Banu-Human First Contact",
        #         "slug": "banu-human-first-contact",
        #         "thumbnail": "https:\/\/cig-galactapedia-prod.s3.amazonaws.com\/upload\/f20bf4e3-15a5-41b5-ada8-2115a4997bec",
        #         "type": "Event",
        #         "rsi_url": "https:\/\/robertsspaceindustries.com\/galactapedia\/article\/VY4Wnv7ZgW-banu-human-first-contact",
        #         "api_url": "https:\/\/api.star-citizen.wiki\/api\/v2\/galactapedia\/VY4Wnv7ZgW",
        #         "categories": [
        #             {
        #                 "id": "0OaeJmxqvO",
        #                 "name": "Exploration"
        #             },
        #             {
        #                 "id": "VyvD5PY1jl",
        #                 "name": "Banu"
        #             },
        #             {
        #                 "id": "boxGg8Bzg1",
        #                 "name": "Politics"
        #             },
        #             {
        #                 "id": "R6vqrLdp2e",
        #                 "name": "Human"
        #             }
        #         ],
        #         "tags": [
        #             {
        #                 "id": "0dQ4O3Myop",
        #                 "name": "banu-human first contact"
        #             },
        #             {
        #                 "id": "bmNr3xa9wP",
        #                 "name": "first contact"
        #             },
        #             {
        #                 "id": "bE3rmGx4aJ",
        #                 "name": "vernon tar"
        #             },
        #             {
        #                 "id": "box5k8dD8Z",
        #                 "name": "davien system"
        #             },
        #             {
        #                 "id": "VaZwadL8Nw",
        #                 "name": "neal socolovich"
        #             }
        #         ],
        #         "properties": [
        #             {
        #                 "name": "type",
        #                 "value": "First contact"
        #             },
        #             {
        #                 "name": "dateS",
        #                 "value": "2438"
        #             },
        #             {
        #                 "name": "location",
        #                 "value": "Davien system"
        #             },
        #             {
        #                 "name": "participants",
        #                 "value": "Humans and Banu"
        #             },
        #             {
        #                 "name": "results",
        #                 "value": "Humans signed the first Interstellar Peace and Trade Accord with an alien civilization"
        #             }
        #         ],
        #         "related_articles": [
        #             {
        #                 "id": "0NwpYPpNZ4",
        #                 "title": "Banu",
        #                 "url": "https:\/\/robertsspaceindustries.com\/galactapedia\/article\/0NwpYPpNZ4-banu",
        #                 "api_url": "https:\/\/api.star-citizen.wiki\/api\/v2\/galactapedia\/0NwpYPpNZ4"
        #             },
        #             {
        #                 "id": "RzPoJ1aP4z",
        #                 "title": "Banu-Human Interstellar Peace Treaty",
        #                 "url": "https:\/\/robertsspaceindustries.com\/galactapedia\/article\/RzPoJ1aP4z-banu-human-interstellar-peace-treaty",
        #                 "api_url": "https:\/\/api.star-citizen.wiki\/api\/v2\/galactapedia\/RzPoJ1aP4z"
        #             }
        #         ],
        #         "translations": {
        #             "en_EN": "Humans and [Banu](https:\/\/robertsspaceindustries.com\/galactapedia\/article\/0NwpYPpNZ4-banu) first made contact in 2438, when navjumper Vernon Tar encountered a Banu fugitive in the outskirts of the [Davien system](https:\/\/robertsspaceindustries.com\/galactapedia\/article\/Rz2g71YlkY-davien-system). After mistakenly opening fire on the Banu vessel, Tar relayed his coordinates to the [United Nations of Earth (UNE)](https:\/\/robertsspaceindustries.com\/galactapedia\/article\/R4ZQpY83oO-united-nations-of-earth). A delegation party led by General [Neal Socolovich](https:\/\/robertsspaceindustries.com\/galactapedia\/article\/VJX7vxG2BG-neal-socolovich) were immediately dispatched to the system to reverse any possible diplomatic fallout and attempt to open communication. Two weeks later, representatives of the [Banu Protectorate](https:\/\/robertsspaceindustries.com\/galactapedia\/article\/Vgg795z2a3-banu-protectorate) arrived in Davien and made formal contact with Socolovich. In October of 2438, [Humans](https:\/\/robertsspaceindustries.com\/galactapedia\/article\/0Nwpnr6wa2-humans) signed their first [Interstellar Peace and Trade Accord](https:\/\/robertsspaceindustries.com\/galactapedia\/article\/RzPoJ1aP4z-banu-human-interstellar-peace-treaty) with an alien civilization.",
        #             "de_DE": "Die Menschen und die [Banu](https:\/\/robertsspaceindustries.com\/galactapedia\/article\/0NwpYPpNZ4-banu) nahmen 2438 zum ersten Mal Kontakt auf, als Navjumper Vernon Tar in den Au\u00dfenbezirken des Davien-Systems auf einen Banu-Fl\u00fcchtling stie\u00df. Nachdem er f\u00e4lschlicherweise das Feuer auf das Banu-Schiff er\u00f6ffnet hatte, \u00fcbermittelte Tar seine Koordinaten an die Vereinten Nationen der Erde (UNE). Eine Delegation unter der Leitung von General Neal Socolovich wurde sofort in das System entsandt, um m\u00f6gliche diplomatische Konsequenzen abzuwenden und zu versuchen, die Kommunikation zu \u00f6ffnen. Zwei Wochen sp\u00e4ter trafen Vertreter des [Banu Protektorats](https:\/\/robertsspaceindustries.com\/galactapedia\/article\/Vgg795z2a3-banu-protectorate) in Davien ein und nahmen formellen Kontakt mit Socolovich auf. Im Oktober 2438 unterzeichneten die Menschen das erste [Interstellare Friedens- und Handelsabkommen](https:\/\/robertsspaceindustries.com\/galactapedia\/article\/RzPoJ1aP4z-banu-human-interstellar-peace-treaty) mit einer au\u00dferirdischen Zivilisation."
        #         },
        #         "created_at": "2021-02-08T00:47:01.000000Z"
        #     },
        #     "meta": {
        #         "processed_at": "2024-05-10 20:39:16",
        #         "valid_relations": [
        #             "categories",
        #             "properties",
        #             "tags",
        #             "related",
        #             "translations"
        #         ]
        #     }
        # }     

            result = {
                "subject_title": api_data["data"]["title"],
                "subject_type": api_data["data"]["type"],
                "description": api_data["data"]["translations"]["en_EN"],
                "additional_information": [
                    {
                        "name": prop["name"],
                        "value": prop["value"]
                    }
                    for prop in api_data["data"]["properties"]
                ],
                "related_articles": [
                    {
                        "title": article["title"],
                        "galactapedia_entry_url": article["api_url"]
                    }
                    for article in api_data["data"]["related_articles"]
                ],
            }

            printr.print(f"Information from the galactapedia: {json.dumps(result, indent=2)}", tags="info")
            if api_data["data"]["related_articles"]:
                self.current_call_identifier = random.randint(0, 1000000)  # Replace with your implementation of generating a confirmation key
                return {"success": True, "additional_instructions": (
                    "You have successfully retrieved information from the galactapedia. "
                    "Give the user a summary of the description. Only provide more details, if he asks for it. "
                    "If there are related articles, tell the user only the titles and ask if he wants more information about those topics. "
                    "If he is interested in the related articles, make subsequent calls using the confirmation key to retrieve more "
                    "information about the related articles. "
                ), "result": result, "call_identifier": self.current_call_identifier}
            else:
                self.current_call_identifier = None
                return {"success": True, "additional_instructions": (
                    "You have successfully retrieved information from the galactapedia. "
                    "Give the user a summary of the description. Only provide more details, if he asks for it. "
                ), "result": result}
                    
        except requests.exceptions.RequestException as e:
            print_debug(f"{self.request_information_from_galactapedia_entry_url.__name__} exception: {str(e)}")
            printr.print(f"Error during request of information from the galactapedia: {str(e)} ", tags="info")
            return {"success": False, "additional_instructions": "You where not able to retrieve information from the galactapedia. Please try again later. ", "error": str(e)}


# ─────────────────────────────────── ↓ TEST ↓ ─────────────────────────────────────────
if __name__ == "__main__":
    lm = LoreManager({},{})
    print("Subclasses of FunctionManager:", FunctionManager.__subclasses__())
    print(lm.get_news_of_the_day({}))
