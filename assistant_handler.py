from openai import AzureOpenAI
import requests

# Azure OpenAI client setup
client = AzureOpenAI(
    api_key="be7f350c1db94430891e3f99b9b70b17",
    api_version="2023-12-01-preview",
    azure_endpoint="https://oai-fusion5-ae.openai.azure.com/"
)

deployment_id = "gpt-4"  # Your deployment name

# Step 1: Define the location you want to query
location = "Piha"  # You can change this dynamically or pass it as a parameter
# Step 2: Call your Flask API with the location
response = requests.get(
    f"https://fishing-agent-hhasa8fzeae8h2ft.australiasoutheast-01.azurewebsites.net/weather-info",
    params={"location": location}
)
weather_data = response.json()

# Step 3: Ask GPT to summarize the fishing conditions
chat_response = client.chat.completions.create(
    model=deployment_id,
    messages=[
        {"role": "system", "content": "You are a fishing assistant that explains weather and tide conditions in simple terms."},
        {"role": "user", "content": f"Here is the weather data for {location}:\n{weather_data}\n\nCan you summarize the fishing conditions for today?"}
    ]
)

# Step 4: Print the assistant's response
print("Assistant:", chat_response.choices[0].message.content)


#Call Examples
#http://127.0.0.1:5050/weather-info?location=Pauanui,%20Coromandel,%20New%20Zealand&days=10