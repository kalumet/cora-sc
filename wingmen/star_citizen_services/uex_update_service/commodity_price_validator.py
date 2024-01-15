import Levenshtein


DEBUG = True


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class CommodityPriceValidator:
    @staticmethod
    def validate_price_information(commodities_price_info_raw, tradeport, operation):
        validated_prices = []
        invalid_prices = []

        if not commodities_price_info_raw.get("commodity_prices", False):
            return "json structure not as expected", None, False

        for commodity_price_info_raw in commodities_price_info_raw["commodity_prices"]:
            print_debug(f"checking {commodity_price_info_raw}")
            if not commodity_price_info_raw.get("commodity_name", False):
                print_debug("missing commodity attribute, skipping")
                continue

            commodity_raw = commodity_price_info_raw.get("commodity_name")

            validated_commodity_key, validated_commodity, success = CommodityPriceValidator.validate_commodity_name(commodity_raw, tradeport)

            if not success:
                print_debug(f"{validated_commodity} ... skipping")
                print_debug("...skipping")
                continue

            # next make plausability check of the provided price, as the recognition can create some inconstistent results

            price_raw = commodity_price_info_raw.get("price_per_unit")
            multiplier = commodity_price_info_raw.get("multiplier")

            new_price, success = CommodityPriceValidator._validate_price(validated_commodity, price_raw, multiplier, operation)

            # inject found information 
            commodity_price_info_raw["code"] = validated_commodity_key
            commodity_price_info_raw["commodity_name"] = validated_commodity["name"]
            
            if not success:
                print_debug(f"{new_price} not plausible ... skipping")
                commodities_price_info_raw["error_reason"] = "price not plausible"
                invalid_prices.append(commodity_price_info_raw)
                
            commodity_price_info_raw["price"] = new_price

            validated_prices.append(commodity_price_info_raw)

        return validated_prices, invalid_prices, True



    @staticmethod
    def _validate_price(validated_commodity, price_to_check, multiplier, operation):
        uex_price = validated_commodity[f"price_{operation}"]

        # we check, if the raw price is within 20% of the current price
        difference = abs(uex_price - price_to_check)

        if difference < 0.2 * uex_price:  # as of uex api tolerance for price changes
            return price_to_check, True
        
        # we can check, if we would be in range, if we apply the given multiplicator
        if multiplier.lower()[0] == "m":
            price_to_check = price_to_check * 1000000
        
        if multiplier.lower()[0] == "k":
            price_to_check = price_to_check * 1000

        difference = abs(uex_price - price_to_check)

        if difference < 0.4 * uex_price:  # prices with 20% variance are ok and will be accepted, higher variance is subject to validation at UEX, we accept up to 40% before we reject.
            return price_to_check, True
        
        # sometimes, we receive . price. instead of 168 for instance 1.68. we try to multiply in 10 steps 2 times and see if we get a plausible price with low variance, then we accept it
        index = 1
        sanitize_price = price_to_check
        while index <= 2:
            sanitize_price = sanitize_price * 10

            difference = abs(uex_price - sanitize_price)

            if difference < 0.2 * uex_price:  # prices with 20% variance are ok 
                return sanitize_price, True
            
            index += 1

        return sanitize_price, False
    


    @staticmethod
    def validate_commodity_name(commodity_raw, tradeport):
        MIN_SIMILARITY_THRESHOLD = 50

        prices = tradeport.get("prices", {})
        matched_commodity = None
        matched_commodity_key = None
        max_commodity_similarity = 0
        for key, commodity in prices.items():
            validated_name = commodity["name"]

            # Check for exact match
            if validated_name == commodity_raw:
                return validated_name, True

            similarity = _calculate_similarity(
                commodity_raw.lower(),
                validated_name.lower(),
                MIN_SIMILARITY_THRESHOLD,
            )
            if similarity > max_commodity_similarity:
                matched_commodity = commodity
                matched_commodity_key = key
                max_commodity_similarity = similarity

        if matched_commodity:
            return matched_commodity_key, matched_commodity, True
        return None, f"could not identify commodity {commodity_raw}", False
    

def _calculate_similarity(str1, str2, threshold):
    distance = Levenshtein.distance(str1, str2)
    similarity = 100 - (100 * distance / max(len(str1), len(str2)))
    return similarity if similarity >= threshold else 0