
from transformers import AutoTokenizer
import torch
import transformers
from transformers import AutoTokenizer, AutoModelForCausalLM

class FineQwenInference:
    def __init__(self, input_text):
        self.input_text = input_text
        self.tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen")
        self.model = AutoModelForCausalLM.from_pretrained("Qwen/Qwen")
        
    def fine_tuned_qwen_response(self):
        prompt = f"Input: {self.input_text}"
        inputs = self.tokenizer(prompt, return_tensors="pt")
        outputs = self.model.generate(**inputs,max_length=100)
        response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        return response  
    
    