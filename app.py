from flask import Flask, render_template, request
import requests
from bs4 import BeautifulSoup as bs
import pandas as pd
import matplotlib.pyplot as plt
from textblob import TextBlob
import os


app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}


def scrape_reviews(query, review_count):
    from urllib.parse import quote_plus
    search_url = "https://www.flipkart.com/search?q=" + quote_plus(query)
    try:
        r = requests.get(search_url, headers=HEADERS, timeout=15)
        r.raise_for_status() 
    except requests.exceptions.Timeout:
        print("⏳ Request timed out")
        return "TIMEOUT_ERROR", None
    except requests.exceptions.ConnectionError:
        print("❌ Connection error")
        return "CONNECTION_ERROR", None
    except requests.exceptions.RequestException as e:
        print("⚠️ General request error:", e)
        return "REQUEST_ERROR", None
    soup = bs(r.text, "html.parser")

    # Category validation (must be Mobiles)
    category_filter = soup.find("a", {"class": "GD4sye ECYCDD"})
    if not category_filter or "Mobiles" not in category_filter.get_text():
        return "INVALID_CATEGORY", None

    # Get first product link
    bigbox=soup.find_all("div",{"class":"cPHDOP col-12-12"})
    valid_products = []
    for box in bigbox:
        if box.find('div', class_='KzDlHZ'):
            valid_products.append(box)
        else:
            print("No Valid Product Found")
    product_link="https://www.flipkart.com"+valid_products[0].div.div.div.a['href']

    # Get product page
    m= requests.get(product_link, headers=HEADERS, timeout=15)
    soup1=bs(m.text, "html.parser")

    # Product title
    title_tag = soup1.find("span", {"class": "VU-ZEz"})
    title = title_tag.get_text(strip=True) if title_tag else "Unknown Product"

    # Go to reviews page link
    review_container = soup1.find("div", {"class": "col pPAw9M"})
    if not review_container:
        print("Review container not found")
        return title, None

    # Now search for the <a> tag with the clean review link inside that container
    review_link_tag = review_container.find("a", href=lambda x: x and "/product-reviews/" in x and "marketplace=FLIPKART" in x)
    if not review_link_tag:
        print("Review link not found inside col pPAw9M")
        return title, None
    review_page_link = "https://www.flipkart.com" + review_link_tag['href']    
    # Go to reviews page page
    n= requests.get(review_page_link, headers=HEADERS, timeout=25)
    soup2=bs(n.text, "html.parser")

    # Loop through reviews
    reviews=[]
    while len(reviews) < review_count:
        n= requests.get(review_page_link, headers=HEADERS, timeout=15)
        soup2=bs(n.text, "html.parser")
        review_blocks = soup2.find_all("div", {"class":"EKFha-"})

        for rb in review_blocks[:10]:
            try:
                review= {
                        "Name" : rb.div.div.find_all('p',{"class":"_2NsDsF AwS1CA"})[0].text,
                        "Rating" : rb.div.div.div.div.text,
                        "Heading" : rb.div.div.div.p.text,
                        "Comment" : rb.div.div.find_all('div',{"class":'row'})[1].div.div.div.text
                }
                reviews.append(review)
                if len(reviews) >= review_count:
                    break   
            except Exception as e:
                print("Error parsing review: ",e)
        # Get next page link
        next_tag = soup2.find('a', {"class": "_9QVEpD"})
        if not next_tag or not next_tag.has_attr('href'):
            break
        review_page_link= "https://www.flipkart.com" + next_tag['href']

    return title, reviews

def classify_sentiment(text):
    analysis=TextBlob(text)
    if analysis.sentiment.polarity>0.3:
        return"Positive"
    elif analysis.sentiment.polarity<0:
        return "Negative"
    else:
        return "Neutral"

def plot_rating_distribution(df):
    rating_counts = df['Rating'].value_counts().sort_index()
    total_count = rating_counts.sum()

    plt.figure(figsize=(6, 4))
    bars = plt.bar(rating_counts.index, rating_counts.values, color='#42A5F5')
    plt.xticks(rating_counts.index)

    # Add labels above bars
    for bar in bars:
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2, height, str(height),
                 ha='center', va='bottom', fontsize=10)

    plt.xlabel('Rating')
    plt.ylabel('Count')
    plt.title(f'Distribution of Ratings\nTotal Ratings: {total_count}')
    plt.tight_layout()
    plt.savefig('static/rating_chart.png')  
    plt.close()

def plot_sentiment_distribution(df):
    sentiment_counts = df['Sentiment'].value_counts().sort_index()

    plt.figure(figsize=(6, 6))
    plt.pie(sentiment_counts.values,
            labels=sentiment_counts.index,
            autopct='%1.1f%%',
            startangle=90,
            colors=['#2ecc71','#f39c12','#e74c3c'])
    plt.axis('equal')
    plt.title('Sentiment Analysis')
    plt.tight_layout()
    plt.savefig('static/sentiment_chart.png')  
    plt.close()


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        product_name = request.form.get("product_name", "").strip()
        if not product_name:
            return render_template("index.html", message="⚠ Please enter a product name")
        review_count=request.form.get("review_count","").strip()
        try:
            review_count = int(review_count)
            if review_count < 10 or review_count % 10 != 0:
                return render_template("index.html", message="⚠ Please enter a multiple of 10 (minimum 10)")
        except ValueError:
            return render_template("index.html", message="⚠ Please enter a valid number of reviews")

        title, reviews = scrape_reviews(product_name, review_count)
        if title == "INVALID_CATEGORY":
            return render_template("index.html", message="⚠ Please enter a product of valid category (Mobiles)")

        if not title:
            return render_template("index.html", message="⚠ No product found")

        if not reviews:
            return render_template("index.html", message="⚠ No reviews found")

        # Convert to DataFrame
        df = pd.DataFrame(reviews)
        df['Rating'] = pd.to_numeric(df['Rating'], errors='coerce')
        df['Sentiment'] = df['Comment'].apply(classify_sentiment)

        # Remove old charts if they exist
        for chart in ['rating_chart.png', 'sentiment_chart.png']:
            path = os.path.join('static', chart)
            if os.path.exists(path):
                os.remove(path)

        # Generate fresh charts
        plot_rating_distribution(df)
        plot_sentiment_distribution(df)

        # Add sentiment back into each review dict
        for i, review in enumerate(reviews):
            review['Sentiment'] = df.loc[i, 'Sentiment']

        return render_template("results.html", title=title, reviews=reviews)


    return render_template("index.html", message=None)

if __name__ == "__main__":
    app.run(debug=True)


