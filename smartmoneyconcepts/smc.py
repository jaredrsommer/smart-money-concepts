from functools import wraps
import pandas as pd
import numpy as np
from pandas import DataFrame, Series


def inputvalidator(input_="ohlc"):
    def dfcheck(func):
        @wraps(func)
        def wrap(*args, **kwargs):
            args = list(args)
            i = 0 if isinstance(args[0], pd.DataFrame) else 1

            args[i] = args[i].rename(columns={c: c.lower() for c in args[i].columns})

            inputs = {
                "o": "open",
                "h": "high",
                "l": "low",
                "c": kwargs.get("column", "close").lower(),
                "v": "volume",
            }

            if inputs["c"] != "close":
                kwargs["column"] = inputs["c"]

            for l in input_:
                if inputs[l] not in args[i].columns:
                    raise LookupError(
                        'Must have a dataframe column named "{0}"'.format(inputs[l])
                    )

            return func(*args, **kwargs)

        return wrap

    return dfcheck


def apply(decorator):
    def decorate(cls):
        for attr in cls.__dict__:
            if callable(getattr(cls, attr)):
                setattr(cls, attr, decorator(getattr(cls, attr)))

        return cls

    return decorate


@apply(inputvalidator(input_="ohlc"))
class smc:
    __version__ = "0.0.15"

    @classmethod
    def fvg(cls, ohlc: DataFrame) -> Series:
        """
        FVG - Fair Value Gap
        A fair value gap is when the previous high is lower than the next low if the current candle is bullish.
        Or when the previous low is higher than the next high if the current candle is bearish.

        returns:
        FVG = 1 if bullish fair value gap, -1 if bearish fair value gap
        Top = the top of the fair value gap
        Bottom = the bottom of the fair value gap
        MitigatedIndex = the index of the candle that mitigated the fair value gap
        """

        fvg = np.where(
            (
                (ohlc["high"].shift(1) < ohlc["low"].shift(-1))
                & (ohlc["close"] > ohlc["open"])
            )
            | (
                (ohlc["low"].shift(1) > ohlc["high"].shift(-1))
                & (ohlc["close"] < ohlc["open"])
            ),
            np.where(ohlc["close"] > ohlc["open"], 1, -1),
            np.nan,
        )

        top = np.where(
            ~np.isnan(fvg),
            np.where(
                ohlc["close"] > ohlc["open"],
                ohlc["low"].shift(-1),
                ohlc["low"].shift(1),
            ),
            np.nan,
        )

        bottom = np.where(
            ~np.isnan(fvg),
            np.where(
                ohlc["close"] > ohlc["open"],
                ohlc["high"].shift(1),
                ohlc["high"].shift(-1),
            ),
            np.nan,
        )

        mitigated_index = np.zeros(len(ohlc), dtype=np.int32)
        for i in np.where(~np.isnan(fvg))[0]:
            mask = np.zeros(len(ohlc), dtype=np.bool_)
            if fvg[i] == 1:
                mask = ohlc["low"][i + 2 :] <= top[i]
            elif fvg[i] == -1:
                mask = ohlc["high"][i + 2 :] >= bottom[i]
            if np.any(mask):
                j = np.argmax(mask) + i + 2
                mitigated_index[i] = j

        mitigated_index = np.where(np.isnan(fvg), np.nan, mitigated_index)

        return pd.concat(
            [
                pd.Series(fvg, name="FVG"),
                pd.Series(top, name="Top"),
                pd.Series(bottom, name="Bottom"),
                pd.Series(mitigated_index, name="MitigatedIndex"),
            ],
            axis=1,
        )

    @classmethod
    def swing_highs_lows(
        cls, ohlc: DataFrame, swing_length: int = 50
    ) -> Series:
        """
        Swing Highs and Lows
        A swing high is when the current high is the highest high out of the swing_length amount of candles before and after.
        A swing low is when the current low is the lowest low out of the swing_length amount of candles before and after.

        parameters:
        swing_length: int - the amount of candles to look back and forward to determine the swing high or low

        returns:
        HighLow = 1 if swing high, -1 if swing low
        Level = the level of the swing high or low
        """

        swing_length *= 2
        # set the highs to 1 if the current high is the highest high in the last 5 candles and next 5 candles
        swing_highs_lows = np.where(
            ohlc["high"]
            == ohlc["high"]
            .shift(-(swing_length // 2))
            .rolling(swing_length)
            .max(),
            1,
            np.where(
                ohlc["low"]
                == ohlc["low"]
                .shift(-(swing_length // 2))
                .rolling(swing_length)
                .min(),
                -1,
                np.nan,
            ),
        )

        continue_ = True
        while continue_:
            positions = np.where(~np.isnan(swing_highs_lows))[0]
            continue_ = False
            for i in range(len(positions) - 1):
                current, next = (
                    swing_highs_lows[positions[i]],
                    swing_highs_lows[positions[i + 1]],
                )
                high, low = (
                    ohlc["high"].iloc[positions[i]],
                    ohlc["low"].iloc[positions[i]],
                )
                next_high, next_low = (
                    ohlc["high"].iloc[positions[i + 1]],
                    ohlc["low"].iloc[positions[i + 1]],
                )
                if current == -1 and next == -1:
                    remove_index = positions[i] if low > next_low else positions[i + 1]
                    swing_highs_lows[remove_index] = np.nan
                    continue_ = True
                elif current == 1 and next == 1:
                    remove_index = (
                        positions[i] if high < next_high else positions[i + 1]
                    )
                    swing_highs_lows[remove_index] = np.nan
                    continue_ = True

        positions = np.where(~np.isnan(swing_highs_lows))[0]
        if swing_highs_lows[positions[0]] == 1:
            swing_highs_lows[0] = -1
        if swing_highs_lows[positions[-1]] == -1:
            swing_highs_lows[-1] = 1

        level = np.where(
            ~np.isnan(swing_highs_lows),
            np.where(swing_highs_lows == 1, ohlc["high"], ohlc["low"]),
            np.nan,
        )

        return pd.concat(
            [
                pd.Series(swing_highs_lows, name="HighLow"),
                pd.Series(level, name="Level"),
            ],
            axis=1,
        )

    @classmethod
    def bos_choch(cls, ohlc: DataFrame, swing_highs_lows: DataFrame, close_break:bool = True) -> Series:
        """
        BOS - Break of Structure
        CHoCH - Change of Character
        these are both indications of market structure changing

        parameters:
        swing_highs_lows: DataFrame - provide the dataframe from the swing_highs_lows function
        close_break: bool - if True then the break of structure will be mitigated based on the close of the candle otherwise it will be the high/low.

        returns:
        BOS = 1 if bullish break of structure, -1 if bearish break of structure
        CHOCH = 1 if bullish change of character, -1 if bearish change of character
        Level = the level of the break of structure or change of character
        BrokenIndex = the index of the candle that broke the level
        """

        level_order = []
        highs_lows_order = []

        bos = np.zeros(len(ohlc), dtype=np.int32)
        choch = np.zeros(len(ohlc), dtype=np.int32)
        level = np.zeros(len(ohlc), dtype=np.float32)

        last_positions = []

        for i in range(len(swing_highs_lows["HighLow"])):
            if not np.isnan(swing_highs_lows["HighLow"][i]):
                level_order.append(swing_highs_lows["Level"][i])
                highs_lows_order.append(swing_highs_lows["HighLow"][i])
                if len(level_order) >= 4:
                    # bullish bos
                    bos[last_positions[-2]] = (
                        1
                        if (
                            np.all(highs_lows_order[-4:] == [-1, 1, -1, 1])
                            and np.all(
                                level_order[-4]
                                < level_order[-2]
                                < level_order[-3]
                                < level_order[-1]
                            )
                        )
                        else 0
                    )
                    level[last_positions[-2]] = (
                        level_order[-3] if bos[last_positions[-2]] != 0 else 0
                    )

                    # bearish bos
                    bos[last_positions[-2]] = (
                        -1
                        if (
                            np.all(highs_lows_order[-4:] == [1, -1, 1, -1])
                            and np.all(
                                level_order[-4]
                                > level_order[-2]
                                > level_order[-3]
                                > level_order[-1]
                            )
                        )
                        else bos[last_positions[-2]]
                    )
                    level[last_positions[-2]] = (
                        level_order[-3] if bos[last_positions[-2]] != 0 else 0
                    )

                    # bullish choch
                    choch[last_positions[-2]] = (
                        1
                        if (
                            np.all(highs_lows_order[-4:] == [-1, 1, -1, 1])
                            and np.all(
                                level_order[-1]
                                > level_order[-3]
                                > level_order[-4]
                                > level_order[-2]
                            )
                        )
                        else 0
                    )
                    level[last_positions[-2]] = (
                        level_order[-3]
                        if choch[last_positions[-2]] != 0
                        else level[last_positions[-2]]
                    )

                    # bearish choch
                    choch[last_positions[-2]] = (
                        -1
                        if (
                            np.all(highs_lows_order[-4:] == [1, -1, 1, -1])
                            and np.all(
                                level_order[-1]
                                < level_order[-3]
                                < level_order[-4]
                                < level_order[-2]
                            )
                        )
                        else choch[last_positions[-2]]
                    )
                    level[last_positions[-2]] = (
                        level_order[-3]
                        if choch[last_positions[-2]] != 0
                        else level[last_positions[-2]]
                    )

                last_positions.append(i)

        broken = np.zeros(len(ohlc), dtype=np.int32)
        for i in np.where(np.logical_or(bos != 0, choch != 0))[0]:
            mask = np.zeros(len(ohlc), dtype=np.bool_)
            # if the bos is 1 then check if the candles high has gone above the level
            if bos[i] == 1 or choch[i] == 1:
                mask = ohlc["close" if close_break else "high"][i + 2 :] > level[i]
            # if the bos is -1 then check if the candles low has gone below the level
            elif bos[i] == -1 or choch[i] == -1:
                mask = ohlc["close" if close_break else "low"][i + 2 :] < level[i]
            if np.any(mask):
                j = np.argmax(mask) + i + 2
                broken[i] = j

        # remove the ones that aren't broken
        for i in np.where(
            np.logical_and(np.logical_or(bos != 0, choch != 0), broken == 0)
        )[0]:
            bos[i] = 0
            choch[i] = 0
            level[i] = 0

        # replace all the 0s with np.nan
        bos = np.where(bos != 0, bos, np.nan)
        choch = np.where(choch != 0, choch, np.nan)
        level = np.where(level != 0, level, np.nan)
        broken = np.where(broken != 0, broken, np.nan)

        bos = pd.Series(bos, name="BOS")
        choch = pd.Series(choch, name="CHOCH")
        level = pd.Series(level, name="Level")
        broken = pd.Series(broken, name="BrokenIndex")

        return pd.concat([bos, choch, level, broken], axis=1)

    @classmethod
    def ob(
        cls,
        ohlc: DataFrame,
        swing_highs_lows: DataFrame,
        close_mitigation:bool = False,
    ) -> DataFrame:
        """
        OB - Order Blocks
        This method detects order blocks when there is a high amount of market orders exist on a price range.

        parameters:
        swing_highs_lows: DataFrame - provide the dataframe from the swing_highs_lows function
        close_mitigation: bool - if True then the order block will be mitigated based on the close of the candle otherwise it will be the high/low.

        returns:
        OB = 1 if bullish order block, -1 if bearish order block
        Top = top of the order block
        Bottom = bottom of the order block
        OBVolume = volume + 2 last volumes amounts
        Percentage = strength of order block (min(highVolume, lowVolume)/max(highVolume,lowVolume))
        """

        crossed = np.full(len(ohlc), False, dtype=bool)
        ob = np.zeros(len(ohlc), dtype=np.int32)
        top = np.zeros(len(ohlc), dtype=np.float32)
        bottom = np.zeros(len(ohlc), dtype=np.float32)
        obVolume = np.zeros(len(ohlc), dtype=np.float32)
        lowVolume = np.zeros(len(ohlc), dtype=np.float32)
        highVolume = np.zeros(len(ohlc), dtype=np.float32)
        percentage = np.zeros(len(ohlc), dtype=np.int32)
        mitigated_index = np.zeros(len(ohlc), dtype=np.int32)
        breaker = np.full(len(ohlc), False, dtype=bool)

        for i in range(len(ohlc)):
            close_index = i
            close_price = ohlc["close"].iloc[close_index]

            # Bullish Order Block
            if len(ob[ob == 1]) > 0:
                for j in range(len(ob) - 1, -1, -1):
                    if ob[j] == 1:
                        currentOB = j
                        if breaker[currentOB]:
                            if ohlc.high.iloc[close_index] > top[currentOB]:
                                ob[j] = top[j] = bottom[j] = obVolume[j] = lowVolume[
                                    j
                                ] = highVolume[j] = mitigated_index[j] = percentage[
                                    j
                                ] = 0.0

                        elif (
                                not close_mitigation
                                and ohlc["low"].iloc[close_index] < bottom[currentOB]
                            ) or (
                                close_mitigation
                                and min(
                                    ohlc["open"].iloc[close_index],
                                    ohlc["close"].iloc[close_index],
                                )
                                < bottom[currentOB]
                            ):
                            breaker[currentOB] = True
                            mitigated_index[currentOB] = close_index - 1
            last_top_index = None
            for j in range(len(swing_highs_lows["HighLow"])):
                if swing_highs_lows["HighLow"][j] == 1 and j < close_index:
                    last_top_index = j
            if last_top_index is not None:
                swing_top_price = ohlc["high"].iloc[last_top_index]
                if close_price > swing_top_price and not crossed[last_top_index]:
                    crossed[last_top_index] = True
                    obBtm = ohlc["high"].iloc[close_index - 1]
                    obTop = ohlc["low"].iloc[close_index - 1]
                    obIndex = close_index - 1
                    for j in range(1, close_index - last_top_index):
                        obBtm = min(
                            ohlc["low"].iloc[last_top_index + j],
                            obBtm,
                        )
                        if obBtm == ohlc["low"].iloc[last_top_index + j]:
                            obTop = ohlc["high"].iloc[last_top_index + j]
                        obIndex = (
                            last_top_index + j
                            if obBtm == ohlc["low"].iloc[last_top_index + j]
                            else obIndex
                        )

                    ob[obIndex] = 1
                    top[obIndex] = obTop
                    bottom[obIndex] = obBtm
                    obVolume[obIndex] = (
                        ohlc["volume"].iloc[close_index]
                        + ohlc["volume"].iloc[close_index - 1]
                        + ohlc["volume"].iloc[close_index - 2]
                    )
                    lowVolume[obIndex] = ohlc["volume"].iloc[close_index - 2]
                    highVolume[obIndex] = (
                        ohlc["volume"].iloc[close_index]
                        + ohlc["volume"].iloc[close_index - 1]
                    )
                    percentage[obIndex] = (
                        np.min([highVolume[obIndex], lowVolume[obIndex]], axis=0)
                        / np.max([highVolume[obIndex], lowVolume[obIndex]], axis=0)
                    ) * 100.0

        for i in range(len(ohlc)):
            close_index = i
            close_price = ohlc["close"].iloc[close_index]

            # Bearish Order Block
            if len(ob[ob == -1]) > 0:
                for j in range(len(ob) - 1, -1, -1):
                    if ob[j] == -1:
                        currentOB = j
                        if breaker[currentOB]:
                            if ohlc.low.iloc[close_index] < bottom[currentOB]:
                                ob[j] = top[j] = bottom[j] = obVolume[j] = lowVolume[
                                    j
                                ] = highVolume[j] = mitigated_index[j] = percentage[
                                    j
                                ] = 0.0

                        elif (
                                not close_mitigation
                                and ohlc["high"].iloc[close_index] > top[currentOB]
                            ) or (
                                close_mitigation
                                and max(
                                    ohlc["open"].iloc[close_index],
                                    ohlc["close"].iloc[close_index],
                                )
                                > top[currentOB]
                            ):
                            breaker[currentOB] = True
                            mitigated_index[currentOB] = close_index
            last_btm_index = None
            for j in range(len(swing_highs_lows["HighLow"])):
                if swing_highs_lows["HighLow"][j] == -1 and j < close_index:
                    last_btm_index = j
            if last_btm_index is not None:
                swing_btm_price = ohlc["low"].iloc[last_btm_index]
                if close_price < swing_btm_price and not crossed[last_btm_index]:
                    crossed[last_btm_index] = True
                    obBtm = ohlc["low"].iloc[close_index - 1]
                    obTop = ohlc["high"].iloc[close_index - 1]
                    obIndex = close_index - 1
                    for j in range(1, close_index - last_btm_index):
                        obTop = max(ohlc["high"].iloc[last_btm_index + j], obTop)
                        obBtm = (
                            ohlc["low"].iloc[last_btm_index + j]
                            if obTop == ohlc["high"].iloc[last_btm_index + j]
                            else obBtm
                        )
                        obIndex = (
                            last_btm_index + j
                            if obTop == ohlc["high"].iloc[last_btm_index + j]
                            else obIndex
                        )

                    ob[obIndex] = -1
                    top[obIndex] = obTop
                    bottom[obIndex] = obBtm
                    obVolume[obIndex] = (
                        ohlc["volume"].iloc[close_index]
                        + ohlc["volume"].iloc[close_index - 1]
                        + ohlc["volume"].iloc[close_index - 2]
                    )
                    lowVolume[obIndex] = (
                        ohlc["volume"].iloc[close_index]
                        + ohlc["volume"].iloc[close_index - 1]
                    )
                    highVolume[obIndex] = ohlc["volume"].iloc[close_index - 2]
                    percentage[obIndex] = (
                        np.min([highVolume[obIndex], lowVolume[obIndex]], axis=0)
                        / np.max([highVolume[obIndex], lowVolume[obIndex]], axis=0)
                    ) * 100.0

        ob = np.where(ob != 0, ob, np.nan)
        top = np.where(~np.isnan(ob), top, np.nan)
        bottom = np.where(~np.isnan(ob), bottom, np.nan)
        obVolume = np.where(~np.isnan(ob), obVolume, np.nan)
        mitigated_index = np.where(~np.isnan(ob), mitigated_index, np.nan)
        percentage = np.where(~np.isnan(ob), percentage, np.nan)

        ob_series = pd.Series(ob, name="OB")
        top_series = pd.Series(top, name="Top")
        bottom_series = pd.Series(bottom, name="Bottom")
        obVolume_series = pd.Series(obVolume, name="OBVolume")
        mitigated_index_series = pd.Series(mitigated_index, name="MitigatedIndex")
        percentage_series = pd.Series(percentage, name="Percentage")

        return pd.concat(
            [
                ob_series,
                top_series,
                bottom_series,
                obVolume_series,
                mitigated_index_series,
                percentage_series,
            ],
            axis=1,
        )

    @classmethod
    def liquidity(cls, ohlc: DataFrame, swing_highs_lows: DataFrame, range_percent:float = 0.01) -> Series:
        """
        Liquidity
        Liquidity is when there are multiply highs within a small range of each other.
        or multiply lows within a small range of each other.

        parameters:
        swing_highs_lows: DataFrame - provide the dataframe from the swing_highs_lows function
        range_percent: float - the percentage of the range to determine liquidity

        returns:
        Liquidity = 1 if bullish liquidity, -1 if bearish liquidity
        Level = the level of the liquidity
        End = the index of the last liquidity level
        Swept = the index of the candle that swept the liquidity
        """

        # subtract the highest high from the lowest low
        pip_range = (max(ohlc["high"]) - min(ohlc["low"])) * range_percent

        # go through all of the high level and if there are more than 1 within the pip range, then it is liquidity
        liquidity = np.zeros(len(ohlc), dtype=np.int32)
        liquidity_level = np.zeros(len(ohlc), dtype=np.float32)
        liquidity_end = np.zeros(len(ohlc), dtype=np.int32)
        liquidity_swept = np.zeros(len(ohlc), dtype=np.int32)

        for i in range(len(ohlc)):
            if swing_highs_lows["HighLow"][i] == 1:
                high_level = swing_highs_lows["Level"][i]
                range_low = high_level - pip_range
                range_high = high_level + pip_range
                temp_liquidity_level = [high_level]
                start = i
                end = i
                swept = 0
                for c in range(i + 1, len(ohlc)):
                    if swing_highs_lows["HighLow"][c] == 1 and range_low <= swing_highs_lows["Level"][c] <= range_high:
                        end = c
                        temp_liquidity_level.append(swing_highs_lows["Level"][c])
                        swing_highs_lows.loc[c, "HighLow"] = 0
                    if ohlc["high"].iloc[c] >= range_high:
                        swept = c
                        break
                if len(temp_liquidity_level) > 1:
                    average_high = sum(temp_liquidity_level) / len(temp_liquidity_level)
                    liquidity[i] = 1
                    liquidity_level[i] = average_high
                    liquidity_end[i] = end
                    liquidity_swept[i] = swept

        # now do the same for the lows
        for i in range(len(ohlc)):
            if swing_highs_lows["HighLow"][i] == -1:
                low_level = swing_highs_lows["Level"][i]
                range_low = low_level - pip_range
                range_high = low_level + pip_range
                temp_liquidity_level = [low_level]
                start = i
                end = i
                swept = 0
                for c in range(i + 1, len(ohlc)):
                    if swing_highs_lows["HighLow"][c] == -1 and range_low <= swing_highs_lows["Level"][c] <= range_high:
                        end = c
                        temp_liquidity_level.append(swing_highs_lows["Level"][c])
                        swing_highs_lows.loc[c, "HighLow"] = 0
                    if ohlc["low"].iloc[c] <= range_low:
                        swept = c
                        break
                if len(temp_liquidity_level) > 1:
                    average_low = sum(temp_liquidity_level) / len(temp_liquidity_level)
                    liquidity[i] = -1
                    liquidity_level[i] = average_low
                    liquidity_end[i] = end
                    liquidity_swept[i] = swept

        liquidity = np.where(liquidity != 0, liquidity, np.nan)
        liquidity_level = np.where(~np.isnan(liquidity), liquidity_level, np.nan)
        liquidity_end = np.where(~np.isnan(liquidity), liquidity_end, np.nan)
        liquidity_swept = np.where(~np.isnan(liquidity), liquidity_swept, np.nan)

        liquidity = pd.Series(liquidity, name="Liquidity")
        level = pd.Series(liquidity_level, name="Level")
        liquidity_end = pd.Series(liquidity_end, name="End")
        liquidity_swept = pd.Series(liquidity_swept, name="Swept")

        return pd.concat([liquidity, level, liquidity_end, liquidity_swept], axis=1)
