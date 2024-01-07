import Levenshtein


DEBUG = True


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class CommodityPriceValidator:
    @staticmethod
    def validate_price_information(commodities_price_info_raw, tradeport, operation):
        validated_prices = []

        if not commodities_price_info_raw.get("commodity_prices", False):
            return "json structure not as expected", False

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

            validated_price, success = CommodityPriceValidator._validate_price(validated_commodity, price_raw, multiplier, operation)

            if not success:
                print_debug(f"{validated_price} ... skipping")
                continue

            # inject found information 
            commodity_price_info_raw["code"] = validated_commodity_key
            commodity_price_info_raw["commodity_name"] = validated_commodity["name"]
            commodity_price_info_raw["price"] = validated_price

            validated_prices.append(commodity_price_info_raw)

        return validated_prices, True



    @staticmethod
    def _validate_price(validated_commodity, price_raw, multiplier, operation):
        price = validated_commodity[f"price_{operation}"]

        # we check, if the raw price is within 20% of the current price
        difference = abs(price - price_raw)

        if difference < 0.2 * price:  # as of uex api tolerance for price changes
            return price, True
        
        # we can check, if we would be in range, if we apply the given multiplicator
        if multiplier.lower() == "m":
            price_raw = price_raw * 1000000
        
        if multiplier.lower() == "k":
            price_raw = price_raw * 1000

        difference = abs(price - price_raw)

        if difference < 0.2 * price:
            return price, True
        
        return f"given price {price_raw} is not plausible for current commodity price {price}", False
    


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