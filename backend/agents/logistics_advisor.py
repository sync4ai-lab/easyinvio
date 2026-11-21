"""Curated, bounded advice: common tasks never incur a model/provider charge."""
import re
from typing import Any


async def advice(request:Any,text:str)->str:
    from backend.agents.supervisor import supervisor
    return await supervisor(request).advisor.answer(text)


class LogisticsAdvisorAgent:
    """Curated fast paths are intentionally model-free and have no tools."""
    async def answer(self,text:str)->str:
        return guidance(text)


def guidance(text:str)->str:
    if re.search(r'\b(?:batter|lithium|prohibited)',text,re.I):
        return ('• Batteries and dangerous goods rules depend on chemistry, whether fitted in equipment, route and service.\n'
                '• Do not send loose, damaged or recalled lithium batteries until the carrier confirms acceptance.\n'
                '• Check the carrier’s current dangerous-goods instructions before booking; this chat does not approve carriage.')
    if re.search(r'\bvolumetric|dimensional weight',text,re.I):
        return ('• Carriers may charge the greater of actual and volumetric weight.\n'
                '• A common example is L×W×H in cm ÷ 5000: 40×30×20 gives 4.8 kg. The service’s actual divisor may differ.\n'
                '• Measure the packed outer box and use live rates for the final charge.')
    if re.search(r'\bcustoms|\bhs code',text,re.I):
        return ('• Describe each item accurately, including material, use, quantity and value.\n'
                '• HS classification, origin, duties and restrictions depend on the goods and destination.\n'
                '• Confirm with the carrier and official customs guidance; suggestions are not a binding customs ruling.')
    return ('• Wrap fragile items separately and protect edges; use a sturdy outer box with cushioning on every side.\n'
            '• Fill empty space so contents cannot move; pack glass away from other items and seal all seams.\n'
            '• Weigh and measure the finished box, and check the carrier’s fragile-item acceptance and protection exclusions.')
